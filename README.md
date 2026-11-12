# StunSail

StunSail is an open-source printer management system that provides a secure, 
easy-to-use interface for managing 3D printers and their associated workflows.

## Overview

StunSail allows you to manage multiple 3D printers through a unified web-based
interface. It handles the complexity of connecting to various printer types,
managing print jobs, monitoring progress, and providing detailed analytics.

## Key Features

- **Multi-Agent Support**: Manage multiple printers with different agents  
- **Secure Operations**: TLS encryption for all communications
- **Minimal Footprint**: Optimized for small systems like Raspberry Pi
- **Easy Installation**: Simple guided installer process
- **Comprehensive Backup/Restore**: Full system state preservation  

## System Components

1. **Core Service** - Main application server that manages printers and jobs
2. **Agent Services** - Per-printer services that communicate with hardware  
3. **Frontend Proxy** - Secure HTTPS endpoint for web access
4. **Certificate Infrastructure** - TLS certificates for secure communication

## Installation

### Prerequisites

- ARM or x86_64 Linux system (tested on Armbian, Raspberry Pi OS)
- At least 256 MiB RAM and 2 GiB storage recommended  
- Python 3.10+ installed
- Root access required for installation

### Quick Installation 

```bash
# Download the installer script
curl -O https://github.com/your-repo/stunsail/releases/latest/download/guided_install.py

# Run as root 
sudo python3 guided_install.py
```

## Architecture

The system consists of several components that work together:

1. **Core Service** (`stunsail-core.service`) - Runs on `localhost:8000`
2. **Agent Services** (`stunsail-agent@printer-name.service`) - Per-printer services  
3. **Frontend Proxy** (`stunsail-frontend.service`) - HTTPS endpoint on port 443
4. **Certificate Authority** - Generates and manages TLS certificates

## Security Model  

StunSail maintains strong security boundaries:
- All communication is encrypted with TLS 
- Core service only listens locally (127.0.0.1:8000)
- Frontend proxy forwards to core securely
- Certificate infrastructure provides secure identity verification  
- No public exposure of printer services

## Certificate Management  

The system automatically generates certificates during installation:

```bash
# Generate CA and server certificates with IP SAN support
python3 generate_ca_and_cert.py \
    --ca-cert /etc/stunsail/certs/ca.crt \
    --ca-key /etc/stunsail/certs/ca.key \
    --server-cert /etc/stunsail/certs/server.crt \
    --server-key /etc/stunsail/certs/server.key \
    --ip-address 192.168.101.50
```

## Uninstall

To completely remove StunSail from your system:

```bash
# Run the full uninstall tool (requires root)
sudo python3 full_uninstall.py
```

This removes all services, configuration files, and certificates.

## Development  

### Getting Started 

1. Clone this repository
2. Install dependencies: `pip install -r requirements.txt`
3. Build documentation: `make docs`  
4. Run tests: `make test`

### Contributing

We welcome contributions! Please see our [contribution guidelines](CONTRIBUTING.md).

## License

This project is licensed under the MIT License - see the LICENSE file for details.