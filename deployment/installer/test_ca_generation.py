#!/usr/bin/env python3
"""Test script to verify CA generation works properly."""

import os
import sys
import tempfile
from pathlib import Path

# Add the current directory to Python path so we can import our module
sys.path.insert(0, str(Path(__file__).parent))

def test_ca_generation():
    """Test that the certificate generation script runs without errors."""
    
    # Change to the directory containing generate_ca.py for imports
    os.chdir(Path(__file__).parent)
    
    try:
        # Import and run the main function from our CA generator
        import generate_ca
        
        # Create a temporary directory for test output
        with tempfile.TemporaryDirectory() as temp_dir:
            old_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                result = generate_ca.main("192.168.101.50")
                print(f"CA generation completed with exit code: {result}")
                
                # Check if certificate files were created
                cert_files = ["ca.crt", "ca.key", "server.crt", "server.key"]
                for file in cert_files:
                    if os.path.exists(file):
                        print(f"✓ Generated {file}")
                    else:
                        print(f"✗ Missing {file}")
                        
            finally:
                os.chdir(old_cwd)
                
        return 0
    except Exception as e:
        print(f"Error running CA generation test: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(test_ca_generation())