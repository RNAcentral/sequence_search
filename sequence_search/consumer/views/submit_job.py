"""
Copyright [2009-2017] EMBL-European Bioinformatics Institute
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
from aiohttp import web
from aiojobs.aiohttp import spawn

from .. import settings
from ..nhmmer_parse import nhmmer_parse
from ..nhmmer_search import nhmmer_search
from ..filenames import query_file_path, result_file_path
from ..producer_client import ProducerClient
from ...db.job_chunk_results import set_job_chunk_results


async def nhmmer(engine, job_id, sequence, database):
    """
    Function that performs nhmmer search and then reports the result to provider API.

    :param engine:
    :param sequence: string, e.g. AAAAGGTCGGAGCGAGGCAAAATTGGCTTTCAAACTAGGTTCTGGGTTCACATAAGACCT
    :param job_id: id of this job, generated by producer
    :param database: name of the database to search against
    :return:
    """

    # TODO: recoverable errors handling
    # TODO: irrecoverable errors handling

    logger = logging.Logger('aiohttp.web')
    logger.info('Job %s spawned' % job_id)

    filename = await nhmmer_search(sequence=sequence, job_id=job_id, database=database)
    logger.info('Nhmmer search finished processing %s' % job_id)

    results = []
    for record in nhmmer_parse(filename=filename):
        results.append(record)

    response_url = "{protocol}://{host}:{port}/{url}".format(
        protocol=settings.PRODUCER_PROTOCOL,
        host=settings.PRODUCER_HOST,
        port=settings.PRODUCER_PORT,
        url=settings.PRODUCER_JOB_DONE_URL
    )

    headers = {'content-type': 'application/json'}

    try:
        await set_job_chunk_results(engine, job_id, database, results)
    except Exception as e:
        return web.HTTPInternalServerError(text=str(e))

    try:
        await ProducerClient().report_job_chunk_done(response_url, headers, job_id, database)
    except Exception as e:
        logger.error('Job %s erred: %s' % (job_id, str(e)))
        return web.HTTPBadGateway(text=str(e))


def validate_job_data(job_id, sequence, database):
    """Ad-hoc validator for input JSON data"""
    if os.path.isfile(query_file_path(job_id, database)) or os.path.isfile(result_file_path(job_id, database)):
        raise web.HTTPBadRequest(text="job with id '%s' has already been submitted" % job_id)

    if database not in settings.RNACENTRAL_DATABASES:
        raise web.HTTPBadRequest(
            text="Database argument is wrong: '%s' is not"
                 " one of RNAcentral databases." % database
        )

    for char in sequence:
        if char not in ['A', 'T', 'G', 'C', 'U']:
            raise web.HTTPBadRequest(
                text="Input sequence should be nucleotide sequence"
                     " and contain only {ATGCU} characters, found: '%s'." % sequence
            )


async def submit_job(request):
    """
    For testing purposes, try the following command:

    curl -H "Content-Type:application/json" -d "{\"job_id\": 1, \"database\": \"miRBase\", \"sequence\": \"AAAAGGTCGGAGCGAGGCAAAATTGGCTTTCAAACTAGGTTCTGGGTTCACATAAGACCT\"}" localhost:8000/submit-job
    """
    logger = logging.Logger('aiohttp.web')

    data = await request.json()
    logger.info('Job %s submitted ' % data['job_id'])
    try:
        job_id = data['job_id']
        sequence = data['sequence']
        database = data['database']
    except (KeyError, TypeError, ValueError) as e:
        raise web.HTTPBadRequest(text='Bad input: %s' % str(e)) from e

    logger.info('Job %s data validated' % data['job_id'])
    validate_job_data(job_id, sequence, database)

    await spawn(request, nhmmer(request.app['engine'], job_id, sequence, database))

    url = request.app.router['result'].url_for(result_id=str(job_id))
    return web.HTTPFound(location=url)
