# Helper script for fetching an OAuth token.

from requests_oauthlib import OAuth2Session

base_url = "https://graph.api.smartthings.com"
redirect_uri = "/oauth/callback"
authorize_uri = base_url + "/oauth/authorize"
token_uri = base_url + "/oauth/token"
endpoint_uri = base_url + "/api/smartapps/endpoints"

scope = ['app']
# Client id and secret are available in "App Settings" in the
# SmartThings SmartApp IDE.
print('Client id and secret are available on the "App Settings" '
      'page of the SmartApp IDE')
client_id = input('Enter the client id: ')
client_secret = input('Enter the client secret: ')

oauth = OAuth2Session(client_id, redirect_uri=redirect_uri, scope=scope)

authorization_url, state = oauth.authorization_url(authorize_uri)

print(('Please go to %s and authorize access; you should then see a 500 error '
      'page.  Copy that URL and paste it at the following prompt.'
      % authorization_url))
authorization_response = input('Enter the full callback URL: ')

token = oauth.fetch_token(
    token_uri,
    authorization_response=authorization_response,
    client_secret=client_secret)

print("Here's the token:")
print(token)
