from sanic import Sanic, exceptions, response

app = Sanic("server80")


# Send all HTTP users to HTTPS
@app.exception(exceptions.NotFound, exceptions.MethodNotSupported)
def redirect_everything_else(request, exception):
    server, path = request.server_name, request.path
    if server and path.startswith("/"):
        return response.redirect(f"https://{server}{path}", status=308)
    return response.text("Bad Request. Please use HTTPS!", status=400)


# ACME challenge for LetsEncrypt
@app.get("/.well-known/acme-challenge/<challenge>")
async def letsencrypt(request, challenge):
    try:
        return response.text(acme_challenges[challenge])
    except KeyError:
        return response.text(f"ACME challenge not found: {challenge}", status=404)


acme_challenges = {}
