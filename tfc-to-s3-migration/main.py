#!/usr/bin/env python3

import argparse
import io
import json
import logging
import os
import re
import sys
from getpass import getuser
from socket import gethostname

import boto3
import requests
from terrasnek.api import TFC
from terrasnek.exceptions import TFCHTTPConflict, TFCHTTPNotFound

THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# Terraform Cloud
TFC_TOKEN = os.getenv("TFC_TOKEN")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG = logging.getLogger()
log_level = logging.getLevelName(LOG_LEVEL)
LOG.setLevel(log_level)

# Set up console handler for logging (https://stackoverflow.com/a/73284328)
ch = logging.StreamHandler()
ch.setLevel(log_level)
LOG.addHandler(ch)

USERNAME = getuser()
HOSTNAME = gethostname()
WS_LOCK_REASON = f"TFC to S3 migration running by {USERNAME}@{HOSTNAME}"
WELL_KNOWN_WORKSPACES = {
    "default",
    "dev",
    "stg",
    "prod",
}


def get_args() -> argparse.Namespace:
    argparser = argparse.ArgumentParser(
        description="""
        Migrate Terraform state files from Terraform Cloud to Amazon S3.

        WARNING! This process will overwrite existing files in target bucket!
        Make sure to backup or enable object versioning.
        """,
        epilog="""
        Environment variables:
            TFC_TOKEN (required)
            LOG_LEVEL (default: `INFO`)
        """,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    argparser.add_argument("-t", "--tfc-org",
                           help="Terraform Cloud organization",
                           default="my-org")
    argparser.add_argument("-b", "--s3-bucket-name",
                           help="target S3 bucket name to upload tfstate files to",
                           default="petstore-terraform-states")
    argparser.add_argument("-s", "--skip-lock",
                           help="""do not lock workspace in TFC
                                (faster but less reliable)""",
                           action="store_true")
    argparser.add_argument("-d", "--cache-dir",
                           help="""path to a directory where to cache
                                downloaded tfstate and metadata files
                                (will create if it doesn't exist;
                                if not provided, disables cache and
                                uploads directly to S3)""")
    # FIXME: see calling code
    # argparser.add_argument("-w", "--search-workspaces",
    #                        help="""comma-separated list of workspace names
    #                             to process""")
    argparser.add_argument("-w", "--search-workspace",
                           help="""name of specific workspace to process
                                (WARNING: TFC API uses fuzzy matching)""")
    argparser.add_argument("-r", "--retry-workspaces-file",
                           help="""path to JSON file with workspaces data
                                to run against (e.g.
                                skipped workspaces JSON file)""",
                           type=argparse.FileType(mode="rb"))
    argparser.add_argument("-l", "--limit-workspaces",
                           help="""limit number of workspaces to process
                                (must be positive integer;
                                0 disables limit)""",
                           type=int,
                           default="0")
    argparser.add_argument("-n", "--dry-run",
                           help="""do not create any resources,
                                only show what would be done""",
                           action="store_true")
    argparser.add_argument("--stats",
                           help="print stats at the end",
                           action="store_true")
    return argparser.parse_args()


def create_tfstate_cache(cache_dir) -> bool:
    """
    Create a cache directory for tfstate files if it doesn't exist.

    Returns `True` on success.
    """
    if not os.path.isdir(cache_dir):
        os.mkdir(cache_dir, mode=0o700)
    return True


def get_tfc_workspaces(search: dict = None, page_size: int = 30) -> tuple:
    page = 1
    while True:
        response = tfc.workspaces.list(page=page,
                                       page_size=page_size,
                                       search=search)
        next_page = response["meta"]["pagination"]["next-page"]
        total_count = response["meta"]["pagination"]["total-count"]
        for workspace in response["data"]:
            yield workspace, total_count
        if not next_page:
            break
        page += 1


def get_tfstate_metadata(workspace_id: str, metadata_file=None,
                         dry_run: bool = False) -> dict:
    """
    Read state metadata from file if it exists,
    otherwise download from TFC and write to file.

    Returns metadata as dict.
    """
    if metadata_file and os.path.isfile(metadata_file):
        LOG.debug("Reading state metadata from file: %s",
                  metadata_file)
        try:
            with open(metadata_file) as f:
                metadata = json.load(f)
        except json.JSONDecodeError:
            LOG.debug("State metadata file is corrupted: %s",
                      metadata_file)
            raise
    else:
        try:
            LOG.debug("Requesting state metadata from TFC")
            metadata = tfc.state_versions.get_current(
                workspace_id
            )["data"]
            # TODO: Add retry if not finalized? Not sure.
            # (https://developer.hashicorp.com/terraform/cloud-docs/api-docs/state-versions#state-version-status)
            # finalized = True \
            #     if metadata["attributes"]["status"] in ["finalized"] \
            #     else False
        except TFCHTTPNotFound:
            LOG.debug("No stored state found in TFC.")
            raise
        if metadata_file and not dry_run:
            LOG.debug("Writing state metadata to file: %s",
                      metadata_file)
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)
            os.chmod(metadata_file, 0o600)
    return metadata


def get_tfstate_content(download_url: str, token: str, tfstate_file=None,
                        dry_run: bool = False) -> bytes:
    """
    Returns tfstate JSON content as bytes.

    If `tfstate_file` is provided, then also
    writes tfstate JSON content to the file.
    """

    # Download tfstate file itself
    LOG.debug("Downloading tfstate from %s", download_url)
    response = requests.get(download_url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/vnd.api+json",
    })
    if response.status_code not in [requests.codes.ok]:
        response.raise_for_status()
    # Copy tfstate file to the cache directory
    if tfstate_file and not dry_run:
        LOG.debug("Writing tfstate to file: %s", tfstate_file)
        with open(tfstate_file, "wb") as f:
            f.write(response.content)
        os.chmod(tfstate_file, 0o600)
    return response.content


def parse_prefixed_workspace(name: str, well_known_workspaces: set) -> tuple:
    """
    Split TFC workspace `name` into prefix and TF OSS CLI workspace name
    based on a list of well known workspace names.

    Example: "backend_svc-dev" -> ("backend_svc", "dev")

    If `name` doesn't match any known workspace names, then it is
    returned as prefix and workspace name is set to `""` (empty string).

    Returns tuple of prefix, workspace name.
    """
    for ws in well_known_workspaces:
        # Determine if the string ends with a known workspace name
        # Alter negative look-behind word boundary to exclude underscore
        if re.search(f"(?<![A-Za-z0-9]){ws}\\b$", name,
                     flags=re.ASCII | re.IGNORECASE):
            return name[:-len(ws) - 1], ws
    return name, ""


def upload_to_s3(bucket: str, key: str, data: bytes,
                 dry_run: bool = False) -> None:
    if not dry_run:
        LOG.debug("Uploading tfstate to bucket %s: %s",
                  bucket, key)
        with io.BytesIO(data) as data:
            s3.Bucket(bucket).upload_fileobj(
                data, key, ExtraArgs={
                    "ServerSideEncryption": "aws:kms"
                })
    else:
        LOG.debug("Would upload tfstate to bucket %s: %s",
                  bucket, key)


def main():
    args = get_args()

    global tfc, s3
    # Create a Terraform Cloud client with token from environment
    tfc = TFC(TFC_TOKEN)
    # Switch to an organization we will be operating in
    tfc.set_org(args.tfc_org)

    # Create an Amazon S3 client
    s3 = boto3.resource("s3")

    if args.dry_run:
        LOG.info(" === DRY RUN MODE === ")

    if args.cache_dir and not args.dry_run:
        if create_tfstate_cache(args.cache_dir):
            LOG.info("Caching tfstate and metadata files to %s",
                     os.path.abspath(args.cache_dir))

    skipped_workspaces = list()
    skipped_workspaces_file = os.path.join(THIS_DIR,
                                           "skipped_workspaces.json")
    uploaded_ws_count = 0
    total_ws_count = 0

    # FIXME: Python doesn't support duplicate keys in dict
    # if args.search_workspaces:
    #     search_workspaces = [ws.strip()
    #                          for ws in args.search_workspaces.split(",")]
    #     workspaces = get_tfc_workspaces(search={
    #         "name": name for name in search_workspaces
    #     })
    if args.search_workspace:
        workspaces = get_tfc_workspaces(search={"name": args.search_workspace})
    elif args.retry_workspaces_file:
        with args.retry_workspaces_file as f:
            retry_workspaces = json.load(f)
        workspaces = ((ws, len(retry_workspaces)) for ws in retry_workspaces)
    else:
        workspaces = get_tfc_workspaces()

    for got_ws, ws in enumerate(workspaces, start=1):
        if args.limit_workspaces == 0:
            pass
        elif got_ws > args.limit_workspaces:
            LOG.info("Reached workspaces limit for testing: %d",
                     args.limit_workspaces)
            break

        ws_name = ws[0]["attributes"]["name"]
        ws_id = ws[0]["id"]
        total_ws_count = ws[1]

        try:
            if not args.skip_lock and not args.dry_run:
                # We temporarily lock state in place to prevent changes
                LOG.info("[%s] Locking workspace", ws_name)
                tfc.workspaces.lock(ws_id, {"reason": WS_LOCK_REASON})

            # Download workspace metadata
            LOG.info("[%s] Fetching metadata", ws_name)
            try:
                if args.cache_dir:
                    metadata_file = os.path.join(args.cache_dir,
                                                 f"{ws_name}.meta.json")
                    metadata = get_tfstate_metadata(ws_id,
                                                    metadata_file,
                                                    dry_run=args.dry_run)
                else:
                    metadata = get_tfstate_metadata(ws_id,
                                                    dry_run=args.dry_run)
            except json.JSONDecodeError:
                LOG.warning("[%s] State metadata file is corrupted! "
                            "Falling back to downloading metadata from TFC.",
                            ws_name)
                metadata = get_tfstate_metadata(ws_id, dry_run=args.dry_run)
            tfstate_url = metadata["attributes"]["hosted-state-download-url"]

            # Download tfstate file content
            LOG.info("[%s] Fetching tfstate file", ws_name)
            if args.cache_dir:
                tfstate_file = os.path.join(args.cache_dir,
                                            f"{ws_name}.tfstate")
                tfstate = get_tfstate_content(tfstate_url,
                                              token=tfc.get_token(),
                                              tfstate_file=tfstate_file,
                                              dry_run=args.dry_run)
            else:
                tfstate = get_tfstate_content(tfstate_url,
                                              token=tfc.get_token(),
                                              dry_run=args.dry_run)
        except KeyboardInterrupt:
            if not args.skip_lock and not args.dry_run:
                LOG.exception("Interrupted; unlocking workspace: %s", ws_name)
                tfc.workspaces.unlock(ws_id)
            sys.exit(130)
        except TFCHTTPNotFound:
            LOG.warning("[%s] Workspace has no stored states! Moving on.",
                        ws_name)
            continue
        except TFCHTTPConflict:
            LOG.warning("[%s] Workspace is locked, skipping.", ws_name)
            if ws[0] not in skipped_workspaces:
                skipped_workspaces.append(ws[0])
            continue
        finally:
            if not args.skip_lock and not args.dry_run:
                LOG.info("[%s] Unlocking workspace", ws_name)
                try:
                    tfc.workspaces.unlock(ws_id)
                except TFCHTTPConflict as err:
                    # Ignore error:
                    # "Workspace already unlocked, or locked by a different user"
                    LOG.debug("Ignoring error: %s", err)
                    pass

        # Prepare object key for S3
        state_name, workspace = parse_prefixed_workspace(
            ws_name, WELL_KNOWN_WORKSPACES
        )
        if not workspace or workspace in ["default"]:
            s3_object_key = f"{state_name}/terraform.tfstate"
        else:
            s3_object_key = f"env:/{workspace}/{state_name}/terraform.tfstate"

        # Upload tfstate to S3
        upload_to_s3(args.s3_bucket_name, s3_object_key, tfstate,
                     dry_run=args.dry_run)
        uploaded_ws_count = got_ws if not args.dry_run else 0
        if not args.dry_run:
            LOG.info("[%s] Uploaded tfstate to bucket %s: %s",
                     ws_name, args.s3_bucket_name, s3_object_key)
        else:
            LOG.info("[%s] Would have uploaded tfstate to bucket %s: %s",
                     ws_name, args.s3_bucket_name, s3_object_key)

        LOG.info("Processed: %d out of %d",
                 got_ws, total_ws_count)

    if skipped_workspaces:
        LOG.debug("Skipped workspaces: %s", [item["attributes"]["name"]
                                             for item in skipped_workspaces])
        LOG.info("Saving list of skipped workspaces to file: %s",
                 skipped_workspaces_file)
        with open(skipped_workspaces_file, "w") as f:
            json.dump(skipped_workspaces, f, indent=2)

    if args.stats:
        LOG.info("Total workspaces: %d", total_ws_count)
        LOG.info("Uploaded workspaces to S3: %d", uploaded_ws_count)
        LOG.info("Skipped workspaces: %d", len(skipped_workspaces))


if __name__ == "__main__":
    main()
