"""Artifact storage interface and implementations."""

import abc
import os
import json
from typing import Any, Dict, Optional
from datetime import datetime

from universal_web_acquisition.artifact.model import Artifact


class ArtifactStorage(abc.ABC):
    """Abstract base class for artifact storage."""
    
    @abc.abstractmethod
    async def store(self, artifact: Artifact) -> Artifact:
        """Store an artifact.
        
        Args:
            artifact: The artifact to store
            
        Returns:
            The stored artifact (may have additional metadata)
        """
        pass
    
    @abc.abstractmethod
    async def retrieve(self, artifact_id: str) -> Optional[Artifact]:
        """Retrieve an artifact by ID.
        
        Args:
            artifact_id: The artifact ID
            
        Returns:
            The artifact if found, None otherwise
        """
        pass
    
    @abc.abstractmethod
    async def delete(self, artifact_id: str) -> bool:
        """Delete an artifact by ID.
        
        Args:
            artifact_id: The artifact ID
            
        Returns:
            True if deleted, False if not found
        """
        pass


class FilesystemArtifactStorage(ArtifactStorage):
    """Filesystem-based artifact storage."""
    
    def __init__(self, base_path: str = "storage"):
        """Initialize the filesystem artifact storage.
        
        Args:
            base_path: Base directory for storing artifacts
        """
        self.base_path = base_path
        self._ensure_base_path()
        
    def _ensure_base_path(self) -> None:
        """Ensure the base path exists."""
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)
            
    def _get_artifact_path(self, artifact_id: str) -> str:
        """Get the filesystem path for an artifact.
        
        Args:
            artifact_id: The artifact ID
            
        Returns:
            Filesystem path for the artifact
        """
        # Use first 2 characters as subdirectory to avoid too many files in one directory
        subdir = artifact_id[:2] if len(artifact_id) >= 2 else "00"
        filename = artifact_id
        return os.path.join(self.base_path, subdir, filename)
        
    def _get_metadata_path(self, artifact_id: str) -> str:
        """Get the filesystem path for artifact metadata.
        
        Args:
            artifact_id: The artifact ID
            
        Returns:
            Filesystem path for the artifact metadata
        """
        artifact_path = self._get_artifact_path(artifact_id)
        return f"{artifact_path}.meta"
        
    async def store(self, artifact: Artifact) -> Artifact:
        """Store an artifact.
        
        Args:
            artifact: The artifact to store
            
        Returns:
            The stored artifact
        """
        artifact_path = self._get_artifact_path(artifact.artifact_id)
        metadata_path = self._get_metadata_path(artifact.artifact_id)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
        
        # Store the content
        with open(artifact_path, 'wb') as f:
            f.write(artifact.content)
            
        # Store the metadata
        metadata = {
            "artifact_id": artifact.artifact_id,
            "job_id": artifact.job_id,
            "url": artifact.url,
            "content_type": artifact.content_type,
            "status_code": artifact.status_code,
            "headers": artifact.headers,
            "created_at": artifact.created_at.isoformat(),
            "size": artifact.size
        }
        
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
            
        return artifact
    
    async def retrieve(self, artifact_id: str) -> Optional[Artifact]:
        """Retrieve an artifact by ID.
        
        Args:
            artifact_id: The artifact ID
            
        Returns:
            The artifact if found, None otherwise
        """
        artifact_path = self._get_artifact_path(artifact_id)
        metadata_path = self._get_metadata_path(artifact_id)
        
        if not os.path.exists(artifact_path) or not os.path.exists(metadata_path):
            return None
            
        try:
            # Load metadata
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
                
            # Load content
            with open(artifact_path, 'rb') as f:
                content = f.read()
                
            # Create artifact
            artifact = Artifact(
                job_id=metadata["job_id"],
                url=metadata["url"],
                content=content,
                content_type=metadata["content_type"],
                status_code=metadata["status_code"],
                headers=metadata["headers"],
                created_at=datetime.fromisoformat(metadata["created_at"]),
                artifact_id=metadata["artifact_id"]
            )
            
            return artifact
        except Exception:
            return None
    
    async def delete(self, artifact_id: str) -> bool:
        """Delete an artifact by ID.
        
        Args:
            artifact_id: The artifact ID
            
        Returns:
            True if deleted, False if not found
        """
        artifact_path = self._get_artifact_path(artifact_id)
        metadata_path = self._get_metadata_path(artifact_id)
        
        deleted = False
        if os.path.exists(artifact_path):
            os.remove(artifact_path)
            deleted = True
            
        if os.path.exists(metadata_path):
            os.remove(metadata_path)
            deleted = True
            
        return deleted
