import pytest
import os
import base64
from app.security.encryption import EncryptionManager, encryption_manager

def test_encryption_manager_initialization(mock_env):
    """Test that EncryptionManager creates a key file if one doesn't exist."""
    key_file = os.environ["ENCRYPTION_KEY_FILE"]
    assert not os.path.exists(key_file)
    
    manager = EncryptionManager()
    
    assert os.path.exists(key_file)
    # Check permissions (on Linux/Mac this would be 600, on Windows it's less strict usually but we just check existence)
    assert manager._master_key is not None

def test_encrypt_decrypt_data(mock_env):
    """Test basic encryption and decryption."""
    manager = EncryptionManager()
    original_text = "Secret Data"
    
    encrypted = manager.encrypt_data(original_text)
    assert encrypted != original_text
    
    decrypted = manager.decrypt_data(encrypted)
    assert decrypted == original_text

def test_encrypt_decrypt_credentials(mock_env):
    """Test dictionary encryption/decryption with sensitive field detection."""
    manager = EncryptionManager()
    
    creds = {
        "project_id": "my-project",
        "api_key": "secret-api-key",
        "client_email": "bot@example.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\n..."
    }
    
    encrypted_creds = manager.encrypt_credentials(creds)
    
    # Check that sensitive fields are encrypted
    assert encrypted_creds["project_id"] == "my-project"  # Not sensitive
    assert encrypted_creds["client_email"] == "bot@example.com" # Not sensitive
    
    assert encrypted_creds["api_key"] != "secret-api-key"
    assert encrypted_creds["private_key"] != "-----BEGIN PRIVATE KEY-----\n..."
    
    # Decrypt and verify
    decrypted_creds = manager.decrypt_credentials(encrypted_creds)
    assert decrypted_creds == creds

def test_is_sensitive_field():
    """Test sensitive field name detection."""
    manager = EncryptionManager()
    
    assert manager._is_sensitive_field("api_key")
    assert manager._is_sensitive_field("MyPassword")
    assert manager._is_sensitive_field("auth_token")
    assert not manager._is_sensitive_field("username")
    assert not manager._is_sensitive_field("project_id")
