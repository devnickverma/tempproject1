import asyncio
import os
import sys

import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
from dotenv import load_dotenv
from loguru import logger

from audio.vad.silero import SileroVADAnalyzer
from frames.frames import BotInterruptionFrame, EndFrame
from pipeline.pipeline import Pipeline
from pipeline.runner import PipelineRunner
from pipeline.task import PipelineParams, PipelineTask
from serializers.protobuf import ProtobufFrameSerializer
from transports.network.websocket_server import (
    WebsocketServerParams,
    WebsocketServerTransport,
)

load_dotenv(override=True)

logger.remove()
logger.add(sys.stderr, level="DEBUG")

class SessionTimeoutHandler:

    def __init__(self, task):
        self.task = task
        self.background_tasks = set()

    async def handle_timeout(self, client_address):
        try:
            logger.info(f"Connection timeout for {client_address}")
            await self.task.queue_frames([BotInterruptionFrame()])
            end_call_task = asyncio.create_task(self._end_call())
            self.background_tasks.add(end_call_task)
            end_call_task.add_done_callback(self.background_tasks.discard)
        except Exception as e:
            logger.error(f"Error during session timeout handling: {e}")

    async def _end_call(self):
        try:
            await asyncio.sleep(15)
            await self.task.queue_frames([BotInterruptionFrame(), EndFrame()])
            logger.info("EndFrame pushed successfully.")
        except Exception as e:
            logger.error(f"Error during call termination: {e}")


async def main():
    transport = WebsocketServerTransport(
        params=WebsocketServerParams(
            serializer=ProtobufFrameSerializer(),
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=True,
            vad_analyzer=SileroVADAnalyzer(),
            session_timeout=60 * 3,
        )
    )

    pipeline = Pipeline(
        [
            transport.input(),
            transport.output(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=16000,
            audio_out_sample_rate=16000,
            allow_interruptions=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        await task.queue_frames([])

    @transport.event_handler("on_session_timeout")
    async def on_session_timeout(transport, client):
        logger.info(f"Session timeout for {client.remote_address}")
        timeout_handler = SessionTimeoutHandler(task)
        await timeout_handler.handle_timeout(client)

    runner = PipelineRunner()

    await runner.run(task)


if __name__ == "__main__":
    asyncio.run(main())
