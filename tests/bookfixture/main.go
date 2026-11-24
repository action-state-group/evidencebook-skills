// Command bookfixture is a test fixture for tests/fresh_env.sh, not part of
// any skill. It does two things the skills never do:
//
//   - seed: put already-sealed tau2 capsules into a jsonl profile's store
//     and evidence book as if `capsulectl cll append` had run at a past time
//     (--at). `capsulectl close` refuses a period that has not ended, so a
//     test that runs in one sitting needs its cases in an earlier, ended
//     week. The records it writes are the ones capsulectl writes for a
//     published capsule; if the two ever drift, `capsulectl cll list` stops
//     showing the seeded cases and the test fails. The book is a single JSONL
//     book (book/log.jsonl) on the library versions of capsulectl-book
//     v0.1.0-rc52 (go.mod). It must be seeded before `capsulectl store init`,
//     which makes a new store a windowed shelf (book/shelf.db) that this
//     fixture does not write.
//   - aac-verify: check an Evidence Bundle with the neutral
//     agent-action-capsule bundle verifier alone, independent of capsulectl.
package main

import (
	"context"
	"crypto/ed25519"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	aacbundle "github.com/action-state-group/agent-action-capsule/go/bundle"
	"github.com/action-state-group/capsule-emit/go/artifact"
	artifactjsonl "github.com/action-state-group/capsule-emit/go/artifact/jsonl"
	"github.com/action-state-group/evidencebook"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "bookfixture:", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	if len(args) == 0 {
		return errors.New("usage: bookfixture seed|aac-verify ...")
	}
	switch args[0] {
	case "seed":
		return seed(args[1:])
	case "aac-verify":
		return aacVerify(args[1:])
	}
	return fmt.Errorf("unknown mode %q", args[0])
}

func seedKey(path string) (ed25519.PrivateKey, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	seed, err := hex.DecodeString(strings.TrimSpace(string(raw)))
	if err != nil || len(seed) != ed25519.SeedSize {
		return nil, fmt.Errorf("%s: not a 32-byte hex seed", path)
	}
	return ed25519.NewKeyFromSeed(seed), nil
}

// seed appends one published-capsule record per artifact.Record file.
func seed(args []string) (err error) {
	fs := flag.NewFlagSet("seed", flag.ContinueOnError)
	store := fs.String("store", "", "the jsonl profile's store directory (before capsulectl store init; the fixture creates it)")
	logID := fs.String("log-id", "", "the profile's log_id")
	operator := fs.String("operator", "", "the profile's operator")
	namespace := fs.String("namespace", "", "the profile's artifact namespace")
	signing := fs.String("signing-key-file", "", "the profile's record signing seed")
	checkpoint := fs.String("checkpoint-key-file", "", "the profile's checkpoint signing seed")
	at := fs.String("at", "", "RFC 3339 commit time for every seeded record")
	if err = fs.Parse(args); err != nil {
		return err
	}
	when, err := time.Parse(time.RFC3339, *at)
	if err != nil {
		return fmt.Errorf("--at: %w", err)
	}
	recordKey, err := seedKey(*signing)
	if err != nil {
		return err
	}
	checkpointKey, err := seedKey(*checkpoint)
	if err != nil {
		return err
	}
	public, ok := recordKey.Public().(ed25519.PublicKey)
	if !ok {
		return errors.New("signing key has no Ed25519 public key")
	}
	ctx := context.Background()
	// capsulectl store init makes a new store a windowed shelf (book/shelf.db), and
	// then reads only that, so records written to book/log.jsonl would be silently
	// ignored. Seed first; store init then keeps the single-book store seeded here.
	if _, err = os.Stat(filepath.Join(*store, "book", "shelf.db")); err == nil {
		return errors.New("the store is a windowed shelf (book/shelf.db), which this fixture does not write: run seed before capsulectl store init")
	}
	if err = os.MkdirAll(*store, 0o700); err != nil {
		return err
	}
	artifacts, err := artifactjsonl.New(filepath.Join(*store, "artifacts.jsonl"), *namespace, []ed25519.PublicKey{public})
	if err != nil {
		return err
	}
	if err = artifacts.Init(ctx); err != nil {
		return err
	}
	signer, err := evidencebook.NewEd25519Signer(recordKey)
	if err != nil {
		return err
	}
	dir := filepath.Join(*store, "book")
	if err = os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	substrate, err := evidencebook.OpenCLL(filepath.Join(dir, "log.jsonl"), *logID, checkpointKey)
	if err != nil {
		return err
	}
	records, err := evidencebook.OpenFileStore(filepath.Join(dir, "records"))
	if err != nil {
		return errors.Join(err, substrate.Release())
	}
	book, err := evidencebook.Open(ctx, evidencebook.Config{
		BookID: *logID, Operator: *operator, Store: records, Substrate: substrate, Originals: evidencebook.SyncedFile(artifacts, filepath.Join(*store, "artifacts.jsonl")), Signer: signer,
		Now: func() time.Time { return when },
	})
	if err != nil {
		return errors.Join(err, records.Release(), substrate.Release())
	}
	defer func() { err = errors.Join(err, book.Release()) }()
	for _, path := range fs.Args() {
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		var record artifact.Record
		if err = json.Unmarshal(raw, &record); err != nil {
			return fmt.Errorf("%s: %w", path, err)
		}
		if _, err = artifact.Verify(record, []ed25519.PublicKey{public}); err != nil {
			return fmt.Errorf("%s: %w", path, err)
		}
		if err = artifacts.Put(ctx, record); err != nil {
			return fmt.Errorf("%s: %w", path, err)
		}
		if _, err = book.Append(ctx, evidencebook.Entry{
			RecordType: "published_capsule", EpistemicType: evidencebook.ProducerClaim,
			SubjectRef: record.CapsuleID,
			Payloads:   [][]byte{record.Capsule, record.ProducerEnvelope},
		}); err != nil {
			return fmt.Errorf("%s: %w", path, err)
		}
	}
	return nil
}

// aacVerify prints the bundle verifier's three claim statuses and fails
// unless all three pass.
func aacVerify(args []string) error {
	if len(args) != 1 {
		return errors.New("usage: bookfixture aac-verify BUNDLE")
	}
	raw, err := os.ReadFile(args[0])
	if err != nil {
		return err
	}
	// Decode keeps integers as json.Number: the verifier's JCS refuses the float64 a plain
	// json.Unmarshal gives the evidence_record_header's integers (v, seq).
	decoded, err := aacbundle.Decode(raw)
	if err != nil {
		return err
	}
	result := aacbundle.VerifyBundle(decoded)
	claims := map[string]aacbundle.ClaimResult{
		"graph_closure": result.GraphClosure, "interval_coverage": result.IntervalCoverage, "per_record_membership": result.PerRecordMembership,
	}
	statuses := map[string]string{}
	for name, claim := range claims {
		statuses[name] = claim.Status
	}
	if err = json.NewEncoder(os.Stdout).Encode(statuses); err != nil {
		return err
	}
	for name, claim := range claims {
		if claim.Status != "pass" {
			return fmt.Errorf("%s: %s %v", name, claim.Status, claim.Findings)
		}
	}
	return nil
}
