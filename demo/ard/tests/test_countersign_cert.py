# SPDX-License-Identifier: Apache-2.0
"""The countersigner's TLS certificate (evidencebook-skills#473): capsulectl, a Go program, connects to the countersigner
with Go's crypto/x509, which refuses an EC key given by explicit curve parameters, as macOS's own openssl (LibreSSL
3.3.6) writes one. The demo makes the certificate itself, on the named curve, and replaces one made before.

``fixtures/explicit-ec-params.crt`` is such a certificate, made on 2026-11-28 by ``/usr/bin/openssl`` (LibreSSL 3.3.6)
with the command countersigner.py ran before #473: ``openssl req -x509 -newkey ec -pkeyopt
ec_paramgen_curve:prime256v1 -nodes -days 365 -subj /CN=localhost -addext subjectAltName=DNS:localhost``."""
from __future__ import annotations

import os
import shutil
import socket
import ssl
import stat
import subprocess
import threading
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

import countersigner as cs
from test_countersign import _party, fake_start  # noqa: F401 (fake_start is a fixture)

_REAL_CERTIFICATE, _REAL_CA_BUNDLE = cs._certificate, cs._ca_bundle
EXPLICIT = Path(__file__).parent / "fixtures" / "explicit-ec-params.crt"

GO_PARSE = """package main

import (
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"os"
)

func main() {
	for _, f := range os.Args[1:] {
		b, err := os.ReadFile(f)
		if err != nil {
			fmt.Println(f, err)
			continue
		}
		p, _ := pem.Decode(b)
		if p == nil {
			fmt.Println(f, "no PEM block")
			continue
		}
		if _, err := x509.ParseCertificate(p.Bytes); err != nil {
			fmt.Println(f, err)
		} else {
			fmt.Println(f, "ok")
		}
	}
}
"""


def _go_parse(tmp_path: Path, *certs: Path) -> dict[str, str]:
    """What Go's x509.ParseCertificate says of each certificate, as capsulectl would parse it. Go is required: the
    local check and CI's ard-demo job both have it, and a skip here would hide the very bug this file is about."""
    go = shutil.which("go")
    if go is None:
        pytest.fail("Go is needed to parse the certificate the way capsulectl does (brew install go)")
    mod = tmp_path / "goparse"
    mod.mkdir()
    (mod / "go.mod").write_text("module goparse\n\ngo 1.21\n")
    (mod / "main.go").write_text(GO_PARSE)
    done = subprocess.run([go, "run", ".", *map(str, certs)], cwd=mod, capture_output=True, text=True, timeout=300,
                          env={**os.environ, "GOFLAGS": "-mod=mod", "GOWORK": "off"})
    assert done.returncode == 0, done.stderr
    return dict(line.split(" ", 1) for line in done.stdout.splitlines())


def test_the_certificate_is_on_the_named_curve_for_localhost(tmp_path):
    cs._certificate(tmp_path)
    der = ssl.PEM_cert_to_DER_cert((tmp_path / "tls.crt").read_text())
    assert cs.P256_NAMED_SPKI in der and cs._certificate_ok(tmp_path)
    cert = x509.load_pem_x509_certificate((tmp_path / "tls.crt").read_bytes())
    assert cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
        x509.DNSName) == ["localhost"]
    key = serialization.load_pem_private_key((tmp_path / "tls.key").read_bytes(), password=None)
    assert key.public_key().public_numbers() == cert.public_key().public_numbers()
    assert stat.S_IMODE((tmp_path / "tls.key").stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))


def test_go_parses_the_demos_certificate_and_refuses_the_one_libressl_made(tmp_path):
    cs._certificate(tmp_path)
    said = _go_parse(tmp_path, tmp_path / "tls.crt", EXPLICIT)
    assert said[str(tmp_path / "tls.crt")] == "ok"
    assert said[str(EXPLICIT)] == "x509: invalid ECDSA parameters"


def test_a_certificate_made_before_the_fix_is_replaced_and_a_good_one_kept(tmp_path):
    shutil.copy(EXPLICIT, tmp_path / "tls.crt")
    (tmp_path / "tls.key").write_text("an old key\n")
    assert not cs._certificate_ok(tmp_path)
    cs._certificate(tmp_path)
    assert cs._certificate_ok(tmp_path)
    made = (tmp_path / "tls.crt").read_bytes(), (tmp_path / "tls.key").read_bytes()
    cs._certificate(tmp_path)
    assert ((tmp_path / "tls.crt").read_bytes(), (tmp_path / "tls.key").read_bytes()) == made


def test_a_certificate_without_its_key_is_remade(tmp_path):
    cs._certificate(tmp_path)
    (tmp_path / "tls.key").unlink()
    assert not cs._certificate_ok(tmp_path)
    cs._certificate(tmp_path)
    assert cs._certificate_ok(tmp_path)


def _serve_once(d: Path) -> int:
    """A TLS listener on localhost serving the folder's certificate for one handshake; returns its port."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(d / "tls.crt", d / "tls.key")
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def accept():
        conn, _ = srv.accept()
        try:
            with ctx.wrap_socket(conn, server_side=True):
                pass
        except (ssl.SSLError, OSError):
            pass
        finally:
            srv.close()
    threading.Thread(target=accept, daemon=True).start()
    return srv.getsockname()[1]


def test_the_bundle_trusts_the_new_certificate(tmp_path):
    """Python's ssl, which start() checks /health with, trusts the certificate through the bundle the parties get
    (with its default context's strict checks on Python 3.13 and later)."""
    cs._certificate(tmp_path)
    cs._ca_bundle(tmp_path, None)
    port = _serve_once(tmp_path)
    ctx = ssl.create_default_context(cafile=str(tmp_path / "ca-bundle.pem"))
    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        with ctx.wrap_socket(raw, server_hostname="localhost") as tls:
            assert tls.getpeercert()["subjectAltName"] == (("DNS", "localhost"),)


def test_a_running_countersigner_on_an_old_certificate_is_restarted_on_a_new_one(tmp_path, monkeypatch, fake_start):
    """A home from before #473 whose countersigner still runs, for the same parties, on the explicit-parameter
    certificate: start() remakes the certificate and the bundle and restarts it; the next start keeps it."""
    d = tmp_path / "countersigner"
    d.mkdir()
    maya = _party(tmp_path, "maya", "deal-cadence/aaaa", "11" * 32)
    # fake_start stubs these two; this test needs the real ones
    monkeypatch.setattr(cs, "_certificate", _REAL_CERTIFICATE)
    monkeypatch.setattr(cs, "_ca_bundle", _REAL_CA_BUNDLE)
    monkeypatch.setattr(cs, "_name_directory", lambda d, parties: None)

    def services():  # fake_start records every Popen, the ps calls of is_ours() too
        return [p for p in fake_start if cs.APP in p.args]
    cs.start(d, [maya], say=lambda *_: None)
    first = services()[0]
    shutil.copy(EXPLICIT, d / "tls.crt")  # as a home made before the fix holds it
    cs.start(d, [maya], say=lambda *_: None)
    assert first.poll() is not None and len(services()) == 2
    assert cs.running(d)["pid"] == services()[1].pid
    assert cs._certificate_ok(d) and (d / "tls.crt").read_text() in (d / "ca-bundle.pem").read_text()
    made = (d / "tls.crt").read_bytes()
    cs.start(d, [maya], say=lambda *_: None)
    assert len(services()) == 2 and (d / "tls.crt").read_bytes() == made
