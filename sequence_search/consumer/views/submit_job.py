"""
Copyright [2009-2019] EMBL-European Bioinformatics Institute
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
     http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import os
import logging
import asyncio
import datetime

from aiohttp import web
from aiojobs.aiohttp import spawn
from itertools import islice

from ..nhmmer_parse import nhmmer_parse
from ..nhmmer_search import nhmmer_search
from ..rnacentral_databases import query_file_path, result_file_path, consumer_validator
from ..settings import MAX_RUN_TIME, NHMMER_LIMIT
from ...db import DatabaseConnectionError, SQLError
from ...db.models import CONSUMER_STATUS_CHOICES, JOB_CHUNK_STATUS_CHOICES
from ...db.job_chunk_results import set_job_chunk_results
from ...db.job_chunks import get_consumer_ip_from_job_chunk, get_job_chunk_from_job_and_database, \
    set_job_chunk_status, set_job_chunk_consumer
from ...db.jobs import update_job_status_from_job_chunks_status
from ...db.consumers import set_consumer_status, set_consumer_job_chunk_id, get_ip


class NhmmerError(Exception):
    def __init__(self, text):
        self.text = text

    def __str__(self):
        return str(self.text)


logger = logging.Logger('aiohttp.web')


async def nhmmer(engine, job_id, sequence, database):
    """
    Function that performs nhmmer search and then reports the result to provider API.

    :param engine:
    :param sequence: string, e.g. AAAAGGTCGGAGCGAGGCAAAATTGGCTTTCAAACTAGGTTCTGGGTTCACATAAGACCT
    :param job_id: id of this job, generated by producer
    :param database: name of the database to search against
    :return:
    """
    job_chunk_id = await get_job_chunk_from_job_and_database(engine, job_id, database)

    logger.info('Nhmmer search started for: job_id = %s, database = %s' % (job_id, database))

    # I assume, subprocess creation can't raise exceptions
    process, filename = await nhmmer_search(sequence=sequence, job_id=job_id, database=database)

    try:
        t0 = datetime.datetime.now()
        task = asyncio.ensure_future(process.communicate())
        await asyncio.wait_for(task, MAX_RUN_TIME)
        logging.debug("Time - Nhmmer searched for sequences in {} for {} seconds".format(
            database, (datetime.datetime.now() - t0).total_seconds())
        )

        return_code = process.returncode
        if return_code != 0:
            raise NhmmerError("Nhmmer process returned non-zero status code")
    except asyncio.TimeoutError as e:
        logger.warning('Nhmmer job chunk timeout out: job_id = %s, database = %s' % (job_id, database))
        process.kill()

        # TODO: what do we do in case we lost the database connection here?
        await set_job_chunk_status(engine, job_id, database, status=JOB_CHUNK_STATUS_CHOICES.timeout)
    except Exception as e:
        logger.error('Nhmmer search error for: job_id = %s, database = %s' % (job_id, database))
        # TODO: what do we do in case we lost the database connection here?
        await set_job_chunk_status(engine, job_id, database, status=JOB_CHUNK_STATUS_CHOICES.error)
    else:
        logger.info('Nhmmer search success for: job_id = %s, database = %s' % (job_id, database))

        try:
            # parse nhmmer results to python (up to the limit set in NHMMER_LIMIT)
            results = list(islice((record for record in nhmmer_parse(filename=filename)), NHMMER_LIMIT))

            # save results of the job_chunk to the database
            if results:
                t0 = datetime.datetime.now()
                await set_job_chunk_results(engine, job_id, database, results)
                logging.debug("Time - saving {} results in {} seconds".format(
                    len(results), (datetime.datetime.now() - t0).total_seconds())
                )
            # set status of the job_chunk to the database
            await set_job_chunk_status(engine, job_id, database, status=JOB_CHUNK_STATUS_CHOICES.success)
        except (DatabaseConnectionError, SQLError) as e:
            # TODO: what do we do in case we lost the database connection here?
            # TODO: probably, clean the nhmmer query and result files?
            pass

    # TODO: what do we do in case we lost the database connection here?
    # update job in the database (maybe the whole job is done)
    await update_job_status_from_job_chunks_status(engine, job_id)

    # TODO: what do we do in case we lost the database connection here?
    # update consumer status and
    consumer_ip = await get_consumer_ip_from_job_chunk(engine, job_chunk_id)
    await set_consumer_status(engine, consumer_ip, CONSUMER_STATUS_CHOICES.available)
    await set_consumer_job_chunk_id(engine, consumer_ip, None, None)


def serialize(request, data):
    """Ad-hoc validator for input JSON data"""
    job_id = data['job_id']
    sequence = data['sequence']
    database = data['database']

    if os.path.isfile(query_file_path(job_id, database)) or os.path.isfile(result_file_path(job_id, database)):
        raise ValueError("job with id '%s' has already been submitted" % job_id)

    consumer_validator(database)

    if not sequence:
        raise ValueError("sequence should be non-empty")
    # TODO: maybe, validate the sequence characters
    # for char in sequence:
    #     if char not in ['A', 'T', 'G', 'C', 'U']:
    #         raise ValueError("Input sequence should be nucleotide sequence "
    #                               "and contain only {ATGCU} characters, found: '%s'." % sequence)

    return data


async def submit_job(request):
    """
    For testing purposes, try the following command:

    curl -H "Content-Type:application/json" -d "{\"job_id\": 1, \"database\": \"mirbase.fasta\", \"sequence\": \"AAAAGGTCGGAGCGAGGCAAAATTGGCTTTCAAACTAGGTTCTGGGTTCACATAAGACCT\"}" localhost:8000/submit-job
    """
    # validate the data
    data = await request.json()
    try:
        data = serialize(request, data)
    except (KeyError, TypeError, ValueError) as e:
        logger.error(e)
        raise web.HTTPBadRequest(text=str(e)) from e

    # cache variables for brevity
    engine = request.app['engine']
    job_id = data['job_id']
    sequence = data['sequence']
    database = data['database']
    consumer_ip = get_ip(request.app)  # 'host.docker.internal'

    # if request was successful, save the consumer state and job_chunk state to the database
    try:
        await set_consumer_status(engine, consumer_ip, CONSUMER_STATUS_CHOICES.busy)
        await set_consumer_job_chunk_id(engine, consumer_ip, job_id, database)
        await set_job_chunk_status(engine, job_id, database, status=JOB_CHUNK_STATUS_CHOICES.started)
        await set_job_chunk_consumer(engine, job_id, database, consumer_ip)
    except (DatabaseConnectionError, SQLError) as e:
        logger.error(e)
        raise web.HTTPBadRequest(text=str(e)) from e

    # spawn nhmmer job in the background and return 201
    await spawn(request, nhmmer(engine, job_id, sequence, database))
    return web.HTTPCreated()
