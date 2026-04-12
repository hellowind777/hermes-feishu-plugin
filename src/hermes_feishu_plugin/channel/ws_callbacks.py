"""WebSocket callback patches for Feishu CardKit actions."""

from __future__ import annotations

import base64
import http
import time
from typing import Any


def patch_feishu_websocket_card_callbacks() -> bool:
    """Route CardKit/card action WS frames into Hermes handlers."""
    try:
        from lark_oapi.ws import client as ws_client_mod
    except Exception:
        return False

    original_handle_data_frame = ws_client_mod.Client._handle_data_frame
    if getattr(original_handle_data_frame, "__hermes_feishu_plugin_wrapped__", False):
        return True

    async def wrapped_handle_data_frame(self: Any, frame: Any):
        headers = frame.headers
        type_ = ws_client_mod._get_by_key(headers, ws_client_mod.HEADER_TYPE)
        message_type = ws_client_mod.MessageType(type_)
        if message_type != ws_client_mod.MessageType.CARD:
            return await original_handle_data_frame(self, frame)

        msg_id = ws_client_mod._get_by_key(headers, ws_client_mod.HEADER_MESSAGE_ID)
        trace_id = ws_client_mod._get_by_key(headers, ws_client_mod.HEADER_TRACE_ID)
        sum_ = ws_client_mod._get_by_key(headers, ws_client_mod.HEADER_SUM)
        seq = ws_client_mod._get_by_key(headers, ws_client_mod.HEADER_SEQ)
        payload = frame.payload
        if int(sum_) > 1:
            payload = self._combine(msg_id, int(sum_), int(seq), payload)
            if payload is None:
                return

        response = ws_client_mod.Response(code=http.HTTPStatus.OK)
        try:
            started_at = int(round(time.time() * 1000))
            result = self._event_handler.do_without_validation(payload)
            finished_at = int(round(time.time() * 1000))
            header = headers.add()
            header.key = ws_client_mod.HEADER_BIZ_RT
            header.value = str(finished_at - started_at)
            if result is not None:
                response.data = base64.b64encode(ws_client_mod.JSON.marshal(result).encode(ws_client_mod.UTF_8))
        except Exception as exc:
            ws_client_mod.logger.error(
                self._fmt_log(
                    "handle message failed, message_type: {}, message_id: {}, trace_id: {}, err: {}",
                    message_type.value,
                    msg_id,
                    trace_id,
                    exc,
                )
            )
            response = ws_client_mod.Response(code=http.HTTPStatus.INTERNAL_SERVER_ERROR)

        frame.payload = ws_client_mod.JSON.marshal(response).encode(ws_client_mod.UTF_8)
        await self._write_message(frame.SerializeToString())

    wrapped_handle_data_frame.__hermes_feishu_plugin_wrapped__ = True
    ws_client_mod.Client._handle_data_frame = wrapped_handle_data_frame
    return True
