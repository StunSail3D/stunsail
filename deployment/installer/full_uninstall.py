#!/usr/bin/env python3
"""
Full uninstall tool for StunSail system with confirmation gating.

This script removes all StunSail components including services, 
configuration files, and certificates while ensuring proper cleanup.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def check_root():
    """Check if we're running as root."""
    if os.geteuid() != 0:
        print("Error: This script must be run as root")
        return False
    return True


def get_systemd_services():
    """Get list of StunSail systemd services."""
    services = []
    
    # Common service patterns for StunSail
    service_patterns = [
        "stunsail-core.service",
        "stunsail-agent@.service", 
        "stunsail-frontend.service"
    ]
    
    try:
        result = subprocess.run(["systemctl", "list-unit-files"], 
                              capture_output=True, text=True, check=True)
        
        for pattern in service_patterns:
            if pattern in result.stdout:
                services.append(pattern)
                
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback - just return the patterns
        pass
    
    return services


def stop_services(services):
    """Stop all StunSail services."""
    print("Stopping services...")
    
    for service in services:
        try:
            subprocess.run(["systemctl", "stop", service], 
                         capture_output=True, check=True)
            print(f"  ✓ Stopped {service}")
        except subprocess.CalledProcessError as e:
            print(f"  ⚠ Failed to stop {service}: {e}")


def disable_services(services):
    """Disable all StunSail services."""
    print("Disabling services...")
    
    for service in services:
        try:
            subprocess.run(["systemctl", "disable", service], 
                         capture_output=True, check=True)
            print(f"  ✓ Disabled {service}")
        except subprocess.CalledProcessError as e:
            print(f"  ⚠ Failed to disable {service}: {e}")


def remove_systemd_units():
    """Remove systemd unit files."""
    print("Removing systemd units...")
    
    unit_paths = [
        "/etc/systemd/system/stunsail-core.service",
        "/etc/systemd/system/stunsail-agent@.service",
        "/etc/systemd/system/stunsail-frontend.service"
    ]
    
    for path in unit_paths:
        if os.path.exists(path):
            try:
                os.remove(path)
                print(f"  ✓ Removed {path}")
            except OSError as e:
                print(f"  ⚠ Failed to remove {path}: {e}")


def cleanup_directories():
    """Remove StunSail directories."""
    print("Cleaning up directories...")
    
    # Directories to remove
    dirs_to_remove = [
        "/opt/stunsail",
        "/etc/stunsail", 
        "/var/lib/stunsail"
    ]
    
    for directory in dirs_to_remove:
        if os.path.exists(directory):
            try:
                shutil.rmtree(directory)
                print(f"  ✓ Removed {directory}")
            except OSError as e:
                print(f"  ⚠ Failed to remove {directory}: {e}")


def cleanup_certificates():
    """Remove certificate files."""
    print("Cleaning up certificates...")
    
    # Certificate directories
    cert_dirs = [
        "/etc/stunsail/certs",
        "/var/lib/stunsail/certs"
    ]
    
    for directory in cert_dirs:
        if os.path.exists(directory):
            try:
                shutil.rmtree(directory)
                print(f"  ✓ Removed {directory}")
            except OSError as e:
                print(f"  ⚠ Failed to remove {directory}: {e}")


def cleanup_systemd_cache():
    """Reload systemd configuration."""
    print("Reloading systemd...")
    try:
        subprocess.run(["systemctl", "daemon-reload"], 
                     capture_output=True, check=True)
        print("  ✓ Systemd reloaded")
    except subprocess.CalledProcessError as e:
        print(f"  ⚠ Failed to reload systemd: {e}")


def verify_cleanup():
    """Verify that cleanup was successful."""
    print("Verifying cleanup...")
    
    # Check for remaining services
    try:
        result = subprocess.run(["systemctl", "list-unit-files"], 
                              capture_output=True, text=True, check=True)
        
        stunsail_found = False
        lines = result.stdout.split('\n')
        for line in lines:
            if 'stunsail' in line.lower():
                print(f"  ⚠ Found StunSail service: {line.strip()}")
                stunsail_found = True
                
        if not stunsail_found:
            print("  ✓ No StunSail services found")
            
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    
    # Check for remaining directories
    dirs_to_check = ["/opt/stunsail", "/etc/stunsail", "/var/lib/stunsail"]
    
    for directory in dirs_to_check:
        if os.path.exists(directory):
            print(f"  ⚠ Found leftover directory: {directory}")
        else:
            print(f"  ✓ Verified clean: {directory}")


def main():
    """Main uninstall function."""
    
    print("StunSail Full Uninstall Tool")
    print("=" * 40)
    
    if not check_root():
        return 1
    
    # Get services to remove
    services = get_systemd_services()
    
    if not services:
        print("No StunSail services found.")
    else:
        print(f"Found services: {', '.join(services)}")
    
    # Confirmation prompt
    print("\nThis will completely remove all StunSail components:")
    print("- All systemd services")
    print("- Configuration files")  
    print("- Certificate files")
    print("- Installed binaries and libraries")
    
    confirm = input("\nDo you want to proceed with full uninstall? (yes/no): ")
    
    if confirm.lower() not in ['yes', 'y']:
        print("Uninstall cancelled.")
        return 0
    
    # Perform cleanup
    stop_services(services)
    disable_services(services)
    remove_systemd_units()
    cleanup_directories()
    cleanup_certificates()
    cleanup_systemd_cache()
    verify_cleanup()
    
    print("\nUninstall completed successfully!")
    print("Please reboot the system to ensure all changes take effect.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())