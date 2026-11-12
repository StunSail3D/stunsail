#!/usr/bin/env python3
"""Test script to verify certificate generation functionality."""

import subprocess
import sys
import tempfile
import os

def test_certificate_generation():
    """Test that our certificate generator works correctly."""
    
    # Create temporary directory for testing
    with tempfile.TemporaryDirectory() as tmpdir:
        ca_cert_path = os.path.join(tmpdir, "ca.crt")
        ca_key_path = os.path.join(tmpdir, "ca.key") 
        server_cert_path = os.path.join(tmpdir, "server.crt")
        server_key_path = os.path.join(tmpdir, "server.key")
        
        # Test command with IP SAN
        cmd = [
            sys.executable, 
            "./generate_ca_and_cert.py",
            "--ca-cert", ca_cert_path,
            "--ca-key", ca_key_path,
            "--server-cert", server_cert_path,
            "--server-key", server_key_path,
            "--ip-address", "192.168.101.50"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            print("Certificate generation successful!")
            print(result.stdout)
            
            # Verify files were created
            for path in [ca_cert_path, ca_key_path, server_cert_path, server_key_path]:
                if os.path.exists(path):
                    print(f"✓ Created: {path}")
                else:
                    print(f"✗ Missing: {path}")
                    return False
                    
            return True
            
        except subprocess.CalledProcessError as e:
            print("Certificate generation failed:")
            print(f"Return code: {e.returncode}")
            print(f"Stdout: {e.stdout}")  
            print(f"Stderr: {e.stderr}")
            return False

if __name__ == "__main__":
    success = test_certificate_generation()
    sys.exit(0 if success else 1)