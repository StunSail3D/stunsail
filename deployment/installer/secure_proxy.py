#!/usr/bin/env python3
"""
Secure proxy implementation for StunSail - minimal HTTPS frontend.
"""

import asyncio
import ssl
from pathlib import Path
import logging

try:
    import aiohttp
    from aiohttp import web
except ImportError as e:
    print(f"Missing dependencies: {e}")
    exit(1)

logger = logging.getLogger(__name__)


class SecureProxy:
    """Secure proxy that forwards requests to core service over HTTPS."""
    
    def __init__(self, 
                 core_host: str = "127.0.0.1",
                 core_port: int = 8000,
                 cert_path: str = "/etc/stunsail/certs/server.crt",
                 key_path: str = "/etc/stunsail/certs/server.key"):
        self.core_host = core_host
        self.core_port = core_port
        self.cert_path = Path(cert_path)
        self.key_path = Path(key_path)
        
        # Create the application
        self.app = web.Application()
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup routes for proxy."""
        self.app.router.add_route("*", "/{path:.*}", self._proxy_request)
        
    async def _proxy_request(self, request):
        """Forward request to core service."""
        try:
            path = request.match_info.get('path', '')
            if not path.startswith('/'):
                path = '/' + path
            
            url = f"http://{self.core_host}:{self.core_port}{path}"
            
            # Prepare headers
            headers = dict(request.headers)
            hop_by_hop_headers = {
                'Connection', 'Keep-Alive', 'Proxy-Authenticate', 
                'Proxy-Authorization', 'TE', 'Trailers', 'Transfer-Encoding',
                'Upgrade'
            }
            
            for header in hop_by_hop_headers:
                headers.pop(header, None)
                
            # Add host header if not present
            if 'Host' not in headers:
                headers['Host'] = f"{self.core_host}:{self.core_port}"
            
            # Handle request body
            data = await request.read()
            
            # Forward to core service
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=request.method,
                    url=url,
                    headers=headers,
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    
                    # Prepare response
                    headers = dict(response.headers)
                    for header in hop_by_hop_headers:
                        headers.pop(header, None)
                        
                    return web.Response(
                        body=await response.read(),
                        status=response.status,
                        headers=headers
                    )
                    
        except Exception as e:
            logger.error(f"Proxy error: {e}")
            raise web.HTTPBadGateway(text="Service unavailable")
    
    def get_ssl_context(self) -> ssl.SSLContext:
        """Get SSL context from certificate files."""
        try:
            # Create SSL context with our certificates
            ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            if self.cert_path.exists() and self.key_path.exists():
                ctx.load_cert_chain(
                    certfile=str(self.cert_path),
                    keyfile=str(self.key_path)
                )
                logger.info(f"Loaded certificates from {self.cert_path} and {self.key_path}")
            else:
                raise FileNotFoundError("Certificate files not found")
            
            # Enable TLS 1.2+ only
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            
            return ctx
            
        except Exception as e:
            logger.error(f"Failed to create SSL context: {e}")
            raise
    
    async def start(self, host: str = "0.0.0.0", port: int = 443):
        """Start the proxy server."""
        try:
            ssl_context = self.get_ssl_context()
            
            runner = web.AppRunner(self.app)
            await runner.setup()
            
            site = web.TCPSite(runner, host, port, ssl_context=ssl_context)
            await site.start()
            
            logger.info(f"Secure proxy started on https://{host}:{port}")
            return site
            
        except Exception as e:
            logger.error(f"Failed to start secure proxy: {e}")
            raise


async def main():
    """Main function - demonstrate usage."""
    try:
        proxy = SecureProxy()
        await proxy.start("0.0.0.0", 443)
        
        # Keep running
        while True:
            await asyncio.sleep(3600)  # Sleep for an hour
            
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        logger.error(f"Error in main: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())