class ProfileResource:
    def __init__(self, client):
        self._client = client

    def get(self):
        return self._client._request("GET", "/profile")
    
    def usage(self):
        return self._client._request("GET", "/profile/usage")