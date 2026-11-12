#!/usr/bin/env python3
"""
Low-footprint HTTPS frontend for StunSail services.
This implements a minimal HTTP server that forwards requests to the core service,
with proper TLS support using our generated certificates.
"""

import asyncio
import ssl
from http import HTTPStatus
from typing import Dict, Any
import json

import aiohttp
from aiohttp import web
import logging


class HTTPSFrontend:
    """Minimal HTTPS frontend for StunSail services."""
    
    def __init__(self, core_host: str = "127.0.0.1", core_port: int = 8000):
        self.core_host = core_host
        self.core_port = core_port
        self.app = web.Application()
        self._setup_routes()
        
    def _setup_routes(self):
        """Setup routes for the frontend."""
        # Forward all requests to the core service
        self.app.router.add_route("*", "/{path:.*}", self._proxy_request)
    
    async def _proxy_request(self, request):
        """Proxy incoming requests to the core service."""
        try:
            # Build target URL
            path = request.match_info.get('path', '')
            if not path.startswith('/'):
                path = '/' + path
                
            url = f"http://{self.core_host}:{self.core_port}{path}"
            
            # Prepare request data
            headers = dict(request.headers)
            # Remove hop-by-hop headers that shouldn't be forwarded
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
            
            # Forward the request to core service
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=request.method,
                    url=url,
                    headers=headers,
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    
                    # Create response for client
                    headers = dict(response.headers)
                    # Remove hop-by-hop headers from response
                    for header in hop_by_hop_headers:
                        headers.pop(header, None)
                        
                    return web.Response(
                        body=await response.read(),
                        status=response.status,
                        headers=headers
                    )
                    
        except aiohttp.ClientError as e:
            logging.error(f"Proxy error: {e}")
            raise web.HTTPBadGateway(text="Service unavailable")
        
        except asyncio.CancelledError:
            # Request was cancelled, re-raise to avoid handling it further
            raise
            
        except Exception as e:
            logging.error(f"Unexpected error in proxy request: {e}")
            return web.HTTPInternalServerError(text="Internal server error")
    
    def run(self, host: str = "0.0.0.0", port: int = 443, ssl_context=None):
        """Run the HTTPS frontend."""
        if not ssl_context:
            # This would normally be set up with our certificates
            raise ValueError("SSL context must be provided")
            
        runner = web.AppRunner(self.app)
        asyncio.run(runner.setup())
        
        site = web.TCPSite(runner, host, port, ssl_context=ssl_context)
        print(f"Starting HTTPS frontend on https://{host}:{port}")
        return site


async def main():
    """Main function to start the HTTPS frontend."""
    
    # In a real implementation, this would:
    # 1. Load SSL certificates
    # 2. Configure service endpoints 
    # 3. Start the server
    
    print("HTTPS Frontend for StunSail services")
    print("This is a placeholder - actual implementation details depend on:")
    print("- Certificate paths (should be in /etc/stunsail/certs/")
    print("- Core service availability at localhost:8000") 
    print("- Service configuration from environment")


if __name__ == "__main__":
    asyncio.run(main())