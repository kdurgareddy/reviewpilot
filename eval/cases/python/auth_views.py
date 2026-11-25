import jwt
from flask import Flask, jsonify, request

app = Flask(__name__)
SECRET = None


def current_user():
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    return jwt.decode(token, options={"verify_signature": False})  # expect: security


@app.route("/admin/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    user = current_user()  # expect: security
    remove_user(user_id)
    return jsonify(ok=True)


def remove_user(user_id):
    ...


if __name__ == "__main__":
    app.run(debug=True)  # expect: security
