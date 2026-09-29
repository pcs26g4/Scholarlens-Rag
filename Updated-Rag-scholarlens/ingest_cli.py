#!/usr/bin/env python3
"""CLI for ingesting Q&A PDFs into Qdrant.

Usage:
  # One or more canonical Question/Answer/Subject PDFs (see qa_content.pdf)
  python ingest_cli.py qa_content.pdf more_qa.pdf

  # A question-paper + suggested-answer pair
  python ingest_cli.py --pair "Chapter1-QP.pdf" "Chapter1-SA.pdf"

  # Mix both, and multiple pairs
  python ingest_cli.py qa_content.pdf \
      --pair "Chapter1-QP.pdf" "Chapter1-SA.pdf" \
      --pair "Chapter2-QP.pdf" "Chapter2-SA.pdf"
"""
import argparse
import sys

from ingestion.ingestion_pdf import main as ingest


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Ingest Q&A PDFs into Qdrant.")
    parser.add_argument(
        "pdfs", nargs="*",
        help="Canonical Question/Answer/Subject PDF(s), e.g. qa_content.pdf"
    )
    parser.add_argument(
        "--pair", nargs=2, action="append", metavar=("QP_PDF", "SA_PDF"),
        default=[],
        help="A question-paper PDF and its matching suggested-answer PDF. Repeatable."
    )
    return parser.parse_args(argv)


def cli(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if not args.pdfs and not args.pair:
        print("No input given. Provide canonical PDF path(s) and/or --pair QP SA.", file=sys.stderr)
        sys.exit(1)
    ingest(pdf_paths=args.pdfs, qp_sa_pairs=[tuple(p) for p in args.pair])


if __name__ == "__main__":
    cli()
