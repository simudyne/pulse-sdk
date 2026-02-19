class ApiKeysResource:
    def __init__(self, client):
        self._client = client
    
    def create(self, name: str):
        return self._client._request("POST", "/api-keys", json={"name": name})
    
    def list(self):
        return self._client._request("GET", "/api-keys")
    
    def revoke(self, key_id: str):
        return self._client._request("DELETE", f"/api-keys/{key_id}")