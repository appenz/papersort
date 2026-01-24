#!/usr/bin/env python3
"""Generate docker.env from .env and JSON credential files.

This script combines the environment variables from .env with the JSON
credential files (dropbox_token.json, service_account_key.json) to create
a single docker.env file suitable for Docker deployment.

Usage:
    python utils/gen_docker_env.py
    # or via make:
    make docker-env
"""

import json
import os
import sys


def main():
    output_lines = []
    
    # Read .env and copy all variables
    if os.path.exists('.env'):
        with open('.env') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if line and not line.startswith('#'):
                    output_lines.append(line)
        print(f"  Read {len(output_lines)} variables from .env")
    else:
        print("  Warning: .env file not found", file=sys.stderr)
    
    # Read and inline dropbox_token.json
    if os.path.exists('dropbox_token.json'):
        with open('dropbox_token.json') as f:
            token_data = json.load(f)
        # Convert to single-line JSON
        json_str = json.dumps(token_data, separators=(',', ':'))
        output_lines.append(f'DROPBOX_TOKEN_JSON={json_str}')
        print("  Added DROPBOX_TOKEN_JSON from dropbox_token.json")
    else:
        print("  Warning: dropbox_token.json not found (Dropbox inbox won't work)", 
              file=sys.stderr)
    
    # Read and inline service_account_key.json
    if os.path.exists('service_account_key.json'):
        with open('service_account_key.json') as f:
            sa_data = json.load(f)
        # Convert to single-line JSON
        json_str = json.dumps(sa_data, separators=(',', ':'))
        output_lines.append(f'GOOGLE_SERVICE_ACCOUNT_JSON={json_str}')
        print("  Added GOOGLE_SERVICE_ACCOUNT_JSON from service_account_key.json")
    else:
        print("  Warning: service_account_key.json not found (Google Drive won't work)", 
              file=sys.stderr)
    
    # Write docker.env
    with open('docker.env', 'w') as f:
        f.write('\n'.join(output_lines) + '\n')
    
    print(f"\nGenerated docker.env with {len(output_lines)} variables")
    print("You can now run: make docker-run")


if __name__ == '__main__':
    main()
