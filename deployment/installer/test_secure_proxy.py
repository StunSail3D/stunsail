#!/usr/bin/env python3
"""
Test script to verify that all components can be imported and run.
"""

import sys

def test_imports():
    """Test that required modules can be imported."""
    
    required_modules = [
        'aiohttp',
        'cryptography'
    ]
    
    missing = []
    
    for module in required_modules:
        try:
            __import__(module)
            print(f"✓ {module} - OK")
        except ImportError as e:
            print(f"✗ {module} - Missing: {e}")
            missing.append(module)
            
    return len(missing) == 0


def test_main():
    """Test main function can be imported."""
    
    try:
        from secure_proxy import SecureProxy, main
        print("✓ SecureProxy class - OK")
        print("✓ main function - OK")
        return True
    except ImportError as e:
        print(f"✗ Main module imports failed: {e}")
        return False


def test_certificate_generation():
    """Test that certificate generation script can be imported."""
    
    try:
        from generate_ca_and_cert import main as cert_main
        print("✓ Certificate generator - OK")
        return True
    except ImportError as e:
        print(f"✗ Certificate generator imports failed: {e}")
        return False


if __name__ == "__main__":
    print("Testing StunSail Components...")
    print("=" * 40)
    
    success = True
    
    if not test_imports():
        success = False
        
    if not test_main():
        success = False
        
    if not test_certificate_generation():
        success = False
        
    print("\n" + "=" * 40)
    if success:
        print("✓ All components tested successfully!")
        sys.exit(0)
    else:
        print("✗ Some components failed tests")
        sys.exit(1)