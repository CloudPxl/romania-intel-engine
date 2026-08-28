#!/bin/bash
zip -r ro-intel-clean.zip . -x "venv/*" "*/__pycache__/*" "romania-intel-frontend/node_modules/*" "romania-intel-frontend/.next/*" ".git/*" "romania-intel-frontend/.git/*" "*.db" "*.env"
