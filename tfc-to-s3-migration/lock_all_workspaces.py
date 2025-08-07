#!/usr/bin/env python3

import argparse
import os

from terrasnek.api import TFC
from terrasnek.exceptions import TFCHTTPConflict

TFC_TOKEN = os.getenv("TFC_TOKEN")

if __name__ == '__main__':
    argparser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    argparser.add_argument("-t", "--tfc-org", default="my-org",
                           help="Terraform Cloud organization")
    argparser.add_argument("-n", "--dry-run", action="store_true")
    args = argparser.parse_args()

    tfc = TFC(TFC_TOKEN)
    tfc.set_org(args.tfc_org)


    def ws_list():
        page = 1
        while True:
            response = tfc.workspaces.list(page=page)
            next_page = response["meta"]["pagination"]["next-page"]
            for workspace in response["data"]:
                yield workspace
            if not next_page:
                break
            page += 1


    for ws in ws_list():
        ws_id, ws_name = ws["id"], ws["attributes"]["name"]
        if not args.dry_run:
            print(f"[{ws_name}] Locking workspace")
            try:
                tfc.workspaces.lock(ws_id, {"reason": "Please switch to S3 backend"})
            except TFCHTTPConflict:
                print(f"[{ws_name}] Workspace is locked, skipping.")
                continue
        else:
            print(f"[DRY RUN] [{ws_name}] Would lock workspace")
