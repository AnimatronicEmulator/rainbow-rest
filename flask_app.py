from flask import Flask, request, render_template, abort
# from flask_cors import CORS
from src.routes import forward, reverse, alerts, almanac, current, forecast
from src.helpers import gen_response, validate, isnum

app = Flask(__name__)
# CORS(app)

ENDPOINTS = {
    "geo": {"forward": forward, "reverse": reverse},
    "wx": {
        "alerts": alerts,
        "almanac": almanac,
        "current": current,
        "forecast": forecast,
    },
}

# Render OpenAPI UI
@app.route("/")
def get_ui():
    return render_template("swaggerui.html")


# Verify that host FWF or docs
@app.before_request
def check_host():
    # TODO delete local from approved
    addr = request.host_url
    approved = ["127.0.0.1:5000", "rainbowrest.xyz", "fairweatherfriend.xyz"]

    if not any([x in addr for x in approved]):
        abort(401)


# Dispatcher for GET requests from any API resource and route
@app.route("/<resource>/<route>")
def dispatcher(resource, route):
    params = request.args.to_dict()

    # Convert lat and lon to floats if they exist
    params["lat"] = isnum(params.pop("lat", None))
    params["lon"] = isnum(params.pop("lon", None))

    # Validate args, return error response if invalid
    v_status = validate(route, **params)
    if v_status != 200:
        return gen_response(v_status)

    # Reset params to those req'd for route
    params = {k: v for k, v in params.items() if v != None}

    response = ENDPOINTS[resource][route](**params)

    return response


if __name__ == "__main__":
    app.run()
