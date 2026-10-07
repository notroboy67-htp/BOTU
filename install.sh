#!/usr/bin/env bash
set -e
sudo apt update
sudo apt install -y python3 python3-venv python3-pip unzip
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp -n .env.example .env || true
echo "Edit .env, then run ./start.sh"
