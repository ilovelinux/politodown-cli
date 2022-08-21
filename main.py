import asyncio
import logging
import pathlib

import aiofiles.os
import aiofiles
import httpx

from tqdm.asyncio import tqdm

from InquirerPy import inquirer
from InquirerPy.validator import EmptyInputValidator

from politodown import session, get_material, get_videostores
from politodown.http import LoginError

from politodown.datatypes import Assignment, Folder, FileNotFound, get_valid_filename, get_relative_path


def retryonfail(func, generator: bool = False):
    async def letstry(*args, **kwargs):
        try:
            await func(*args, **kwargs)
        except (httpx.ConnectTimeout, httpx.ConnectError, httpx.RemoteProtocolError, httpx.HTTPStatusError) as e:
            logging.warning(e)
            await asyncio.sleep(5)
            await letstry(*args, **kwargs)
        except Exception as e:
            logging.error(e)
            raise
    return letstry


class postfix:
    def __init__(self, string: str):
        self.string = string
    def __str__(self) -> str:
        return self.string

@retryonfail
async def download(inc, basepath: pathlib.Path):
    bar_format = "{l_bar}{bar}| {n_fmt}/{total_fmt} [{postfix}]"

    if isinstance(inc, Assignment):
        filecount = 0
        async for _ in inc.files(True):
            filecount += 1
        pbar = tqdm(inc.files(True), total=filecount, position=0, bar_format=bar_format)
    else:
        pbar = tqdm((await inc.videolessons()).values(), total=len(await inc.videolessons()), position=0, bar_format=bar_format)
    async for file in pbar:
        path = basepath/get_relative_path(file)
        await aiofiles.os.makedirs(path.parent, exist_ok=True)

        if path.parent.stem != get_valid_filename(inc.name):
            pbar.postfix = postfix(path.parent.stem)

        with tqdm(total=1, position=1, leave=False, unit='B',
                  unit_scale=True, unit_divisor=1024,
                  postfix={"file": file.name[-10:]}) as dbar:
            try:
                async for chunk_length in file.save(path.parent, lambda file: file.name if isinstance(file.parent, Folder) else file.filename):
                    if chunk_length == -1:
                        logging.info("%s skipped", path)
                        continue
                    dbar.total = file.size
                    dbar.update(chunk_length)
            except FileNotFound:
                logging.warning("%s not found", path)

async def login(username: str, password: str) -> bool:
    await session.signin(username, password)


async def main():
    username = await inquirer.text(message="Username:").execute_async()
    password = await inquirer.secret(
        message="Password:",
        transformer=lambda _: "[hidden]",
    ).execute_async()

    try:
        await login(username, password)
    except LoginError as e:
        await inquirer.text(
            f"Login error: {e}",
            instruction="Press enter to continue.",
            mandatory=False,
        ).execute_async()
        return await main()

    await home()


async def home():
    choosetype = await inquirer.select(
        message="Choose type:",
        choices=[
            "Materiali",
            "Videolezioni",
        ],
    ).execute_async()

    year = await inquirer.number(
        message="Year:",
        min_allowed=2002,
        max_allowed=2022,
        default=2022,
        validate=EmptyInputValidator(),
    ).execute_async()

    year = int(year)

    if choosetype == "Materiali":
        await choose_material(await get_material(year))
    else:
        await videostores(await get_videostores(year))


async def choose_material(mat):
    answer = await inquirer.fuzzy(
        message="Choose material:",
        choices=mat.keys(),
    ).execute_async()

    material = mat[answer]

    _assignments = await material.assignments()
    await assignments(_assignments)


async def assignments(assignments):
    answer = await inquirer.fuzzy(
        message="Choose assignments:",
        choices=assignments.keys(),
    ).execute_async()

    inc = assignments[answer]

    await download(inc, pathlib.Path("Materiali"))


async def videostores(vid):
    videostore = await inquirer.select(
        message="Choose videostore collection:",
        choices=vid.keys(),
    ).execute_async()

    answer = await inquirer.fuzzy(
        message="Choose videostore:",
        choices=vid[videostore].keys(),
    ).execute_async()

    await download(vid[videostore][answer], pathlib.Path("Videolezioni"))


asyncio.run(main())
