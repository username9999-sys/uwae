"""HTTP transport adapter interface and implementation."""

import abc
from typing import Any, Dict, Optional
import httpx
from urllib.parse import urljoin, urlparse

from universal_web_acquisition.core.job_model import Job
from universal_web_acquisition.artifact.model import Artifact
from universal_web_acquisition.artifact.storage import ArtifactStorage


class TransportAdapter(abc.ABC):
    """Abstract base class for transport adapters."""
    
    @abc.abstractmethod
    async def acquire(self, job: Job, storage: ArtifactStorage) -> Artifact:
        """Acquire content from a URL.
        
        Args:
            job: The job to execute
            storage: The artifact storage to use
            
        Returns:
            The acquired artifact
        """
        pass
    
    @abc.abstractmethod
    def can_handle(self, url: str) -> bool:
        """Check if this adapter can handle a URL.
        
        Args:
            url: The URL to check
            
        Returns:
            True if this adapter can handle the URL
        """
        pass


class HTTPTransportAdapter(TransportAdapter):
    """HTTP transport adapter using httpx."""
    
    def __init__(self, timeout: float = 30.0, verify_ssl: bool = True, 
                 user_agent: str = "UniversalWebAcquisitionEngine/0.1.0"):
        """Initialize the HTTP transport adapter.
        
        Args:
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
            user_agent: User agent string to use
        """
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.user_agent = user_agent
        
    async def acquire(self, job: Job, storage: ArtifactStorage) -> Artifact:
        """Acquire content from a URL using HTTP.
        
        Args:
            job: The job to execute
            storage: The artifact storage to use
            
        Returns:
            The acquired artifact
        """
        headers = {
            "User-Agent": self.user_agent
        }
        
        async with httpx.AsyncClient(
            timeout=self.timeout,
            verify=self.verify_ssl,
            follow_redirects=True
        ) as client:
            response = await client.get(
                job.url,
                headers=headers
            )
            
            # Raise an exception for bad status codes
            response.raise_for_status()
            
            # Create artifact from the response
            artifact = Artifact(
                job_id=job.job_id,
                url=str(response.url),  # Final URL after redirects
                content=response.content,
                content_type=response.headers.get("content-type", "application/octet-stream"),
                status_code=response.status_code,
                headers=dict(response.headers)
            )
            
            # Store the artifact
            stored_artifact = await storage.store(artifact)
            return stored_artifact
    
    def can_handle(self, url: str) -> bool:
        """Check if this adapter can handle a URL.
        
        Args:
            url: The URL to check
            
        Returns:
            True if this adapter can handle the URL
        """
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https")


# Registry of available transports
TRANSPORT_REGISTRY = {
    "http": HTTPTransportAdapter,
    "https": HTTPTransportAdapter
}


def get_transport_for_url(url: str) -> Optional[TransportAdapter]:
    """Get an appropriate transport adapter for a URL.
    
    Args:
        url: The URL to get a transport for
        
    Returns:
        A transport adapter instance or None if no adapter can handle the URL
    """
    for transport_class in TRANSPORT_REGISTRY.values():
        transport = transport_class()
        if transport.can_handle(url):
            return transport
    return None
