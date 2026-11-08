from temporalio import activity


@activity.defn
async def say_hello(name: str) -> str:
    activity.logger.info("Saying hello to %s", name)
    return f"Hello, {name}!"
