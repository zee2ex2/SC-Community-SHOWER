#!/bin/bash
# Azure App Service startup script for SC SHOWER

pip install -r requirements.txt
python server.py
