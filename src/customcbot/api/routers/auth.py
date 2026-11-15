"""Signing in and out, and setting the password."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ...exceptions import InvalidInputError
from .. import auth

router = APIRouter(prefix="/api")


class LoginBody(BaseModel):
    password: str


class PasswordBody(BaseModel):
    new_password: str = ""  # empty removes the password
    current_password: str = ""


def _status(request: Request) -> dict:
    return {
        "required": auth.required(),
        "signed_in": auth.signed_in(request.cookies.get(auth.COOKIE)),
        "fixed": bool(auth.from_environment()),  # set where the app is started; not changeable here
    }


def _remember(response: Response) -> None:
    response.set_cookie(auth.COOKIE, auth.session_token(), httponly=True, samesite="strict", max_age=60 * 60 * 24 * 30)


@router.get("/auth/status")
def status(request: Request) -> dict:
    return _status(request)


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    if not auth.matches(body.password):
        time.sleep(1)  # slows down guessing
        raise InvalidInputError("That is not the right password.")
    _remember(response)
    return {"required": auth.required(), "signed_in": True, "fixed": bool(auth.from_environment())}


@router.post("/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@router.put("/auth/password")
def change_password(body: PasswordBody, request: Request, response: Response) -> dict:
    """Set, change or remove the password. Changing one that exists needs the current one."""
    if auth.required() and not auth.matches(body.current_password):
        time.sleep(1)
        raise InvalidInputError("The current password is not right.")
    auth.set_password(body.new_password)
    if auth.required():
        _remember(response)  # stay signed in on this device
    else:
        response.delete_cookie(auth.COOKIE)
    return {"required": auth.required(), "signed_in": True, "fixed": False}
