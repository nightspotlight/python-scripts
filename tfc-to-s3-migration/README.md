# tfc-to-s3-migration

This script is designated to migrate Terraform state files from Terraform Cloud (TFC) to a bucket in Amazon S3.

It parses workspace names in TFC into specific S3 paths based on known workspace suffixes (dev, stg, prod, etc). E.g. `petstore_frontend-dev` will be uploaded to S3 at path `env:/dev/petstore_frontend/terraform.tfstate`. This assumes that [`workspace_key_prefix`](https://developer.hashicorp.com/terraform/language/settings/backends/s3#workspace_key_prefix) in Terraform's S3 backend configuration is left at default value.

## Requirements

### Python

Developed and tested with Python 3.11 on macOS 14.2.

### AWS CLI

AWS CLI must be installed with [access credentials configured](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-quickstart.html).

### Terraform

Terraform must be installed and [logged into Terraform Cloud](https://developer.hashicorp.com/terraform/cli/commands/login).

### Amazon S3

A target bucket must already exist (default name: `petstore-terraform-states`).

## Usage

```bash
export AWS_PROFILE=petstore
export AWS_REGION=eu-central-1

python3 -m venv .venv
source .venv/bin/activate
pip install -U -r requirements.txt

terraform login
export TFC_TOKEN="$(jq -crM '.credentials."app.terraform.io".token' ~/.terraform.d/credentials.tfrc.json)"

python3 ./main.py --help
# long options shown
python3 ./main.py \
--tfc-org petstore-testing \
--s3-bucket-name petstore-terraform-states-test \
--cache-dir tfstates \
--limit-workspaces 3 \
--dry-run
```

```plaintext
usage: main.py [-h] [-t TFC_ORG] [-b S3_BUCKET_NAME] [-s] [-d CACHE_DIR] [-w SEARCH_WORKSPACE]
               [-r RETRY_WORKSPACES_FILE] [-l LIMIT_WORKSPACES] [-n] [--stats]

Migrate Terraform state files from Terraform Cloud to Amazon S3. WARNING! This process will
overwrite existing files in target bucket! Make sure to backup or enable object versioning.

options:
  -h, --help            show this help message and exit
  -t TFC_ORG, --tfc-org TFC_ORG
                        Terraform Cloud organization (default: my-org)
  -b S3_BUCKET_NAME, --s3-bucket-name S3_BUCKET_NAME
                        target S3 bucket name to upload tfstate files to (default: petstore-
                        terraform-states)
  -s, --skip-lock       do not lock workspace in TFC (faster but less reliable) (default: False)
  -d CACHE_DIR, --cache-dir CACHE_DIR
                        path to a directory where to cache downloaded tfstate and metadata files
                        (will create if it doesn't exist; if not provided, disables cache and
                        uploads directly to S3) (default: None)
  -w SEARCH_WORKSPACE, --search-workspace SEARCH_WORKSPACE
                        name of specific workspace to process (WARNING: TFC API uses fuzzy
                        matching) (default: None)
  -r RETRY_WORKSPACES_FILE, --retry-workspaces-file RETRY_WORKSPACES_FILE
                        path to JSON file with workspaces data to run against (e.g. skipped
                        workspaces JSON file) (default: None)
  -l LIMIT_WORKSPACES, --limit-workspaces LIMIT_WORKSPACES
                        limit number of workspaces to process (must be positive integer; 0
                        disables limit) (default: 0)
  -n, --dry-run         do not create any resources, only show what would be done (default: False)
  --stats               print stats at the end (default: False)

Environment variables: TFC_TOKEN (required) LOG_LEVEL (default: `INFO`)
```
