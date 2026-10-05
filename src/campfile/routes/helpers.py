"""Shared route helpers."""

from dataclasses import asdict

from flask import jsonify


def present(obj):
    return jsonify(asdict(obj))


def present_list(objs):
    return jsonify([asdict(o) for o in objs])


def error(message, code):
    return jsonify({"error": message}), code


def current_uid(args, default):
    try:
        return int(args.get("as", default))
    except ValueError:
        return default
