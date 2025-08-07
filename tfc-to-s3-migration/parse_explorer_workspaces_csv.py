#!/usr/bin/env python3

import argparse
import csv
import json
import sys
from collections import defaultdict

from main import parse_prefixed_workspace, WELL_KNOWN_WORKSPACES


def get_args():
    argparser = argparse.ArgumentParser(
        description="""Takes as input a CSV file downloaded from Terraform Cloud / Explorer / Workspaces
                    (https://developer.hashicorp.com/terraform/cloud-docs/workspaces/explorer).
                    
                    Parses occurrences under `workspace_name` field
                    into prefix (state name) and workspace name,
                    then groups each prefix under its respective workspace.
                    
                    Outputs lists of prefixes mapped to workspaces in a format of preference.
                    """
    )
    argparser.add_argument("input_file",
                           help="TFC Explorer CSV file to parse")
    argparser.add_argument("-o", "--output-file",
                           help="""save output in the specified file
                                instead of stdout""",
                           type=argparse.FileType("w"),
                           default=sys.stdout)
    argparser.add_argument("--output-format",
                           choices=["text", "table", "json"],
                           default="text")
    argparser.add_argument("--sort",
                           help="sort all items in output",
                           action="store_true")
    return argparser.parse_args()


def read_csv(input_file):
    with open(input_file, newline='') as f:
        dialect = csv.Sniffer().sniff(f.read(1024), ",")
        f.seek(0)
        reader = csv.DictReader(f, dialect=dialect)
        for row in reader:
            yield row


if __name__ == '__main__':
    args = get_args()

    ws_dict = defaultdict(list)
    for row in read_csv(args.input_file):
        state_name, workspace = parse_prefixed_workspace(row["workspace_name"],
                                                         WELL_KNOWN_WORKSPACES)
        ws_dict[workspace if workspace else "default"].append(state_name)

    if args.sort:
        ws_dict = {k: [i for i in sorted(v)] for k, v in sorted(ws_dict.items())}

    if args.output_format == "json":
        print(json.dumps(ws_dict), file=args.output_file)
    elif args.output_format == "text":
        for ws, states in ws_dict.items():
            for state in states:
                print(ws, state, sep="\t", file=args.output_file)
    else:
        raise NotImplementedError(
            f"output format \"{args.output_format}\" is not implemented yet")
