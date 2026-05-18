#!/bin/bash
# Azure App Service startup script for SC SHOWER
# All config is via environment variables set in the Azure portal

# Install dependencies
pip install -r requirements.txt

# Start the server
python server.py
