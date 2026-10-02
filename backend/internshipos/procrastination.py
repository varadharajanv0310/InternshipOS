"""Optional persistent PostgreSQL worker. Free CI invokes the same bounded tick directly."""
import os
import procrastinate
from .jobs import run_tick

url=os.getenv('DATABASE_URL','')
if not url.startswith(('postgres://','postgresql://','postgresql+psycopg://')):
    raise RuntimeError('The persistent Procrastinate worker requires PostgreSQL. Use the batch/local worker for portable development.')
conninfo=url.replace('postgresql+psycopg://','postgresql://',1)
app=procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=conninfo))

@app.periodic(cron='0 * * * *',periodic_id='internshipos-due-work')
@app.task(name='internshipos.tick',queue='internshipos',lock='internshipos-tick',retry=2)
def due_work(timestamp:int):
    return run_tick()
