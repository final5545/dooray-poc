"""
A simple echo agent using Dooray SDK

Author: wonseokjeong
"""
import os

from dotenv import load_dotenv

from dooray_sdk import Agent

# Load environment variables from .env file
load_dotenv()

# Create agent instance
agent = Agent(
    token=os.getenv("DOORAY_AGENT_TOKEN"),
    domain=os.getenv("DOORAY_DOMAIN", "infomax.dooray.com"),
)


@agent.messenger
async def echo_handler(req):
    """
    Echo agent handler.

    Receives a message and replies with the same content.
    """
    # Skip if no text content
    if not req.text:
        return

    # Echo the message back
    await req.reply(f"Echo: {req.text}")


if __name__ == "__main__":
    print("Starting dooray_agent...")
    print(f"Domain: {agent.domain}")
    agent.run()
