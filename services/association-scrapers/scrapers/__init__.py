"""
Knock association scrapers.
Each module exposes a main scrape function: scrape_<name>(db_conn, limit=None)
"""

from scrapers.acsi import scrape_acsi
from scrapers.catholic import scrape_catholic
from scrapers.jewish import scrape_jewish
from scrapers.episcopal import scrape_episcopal
from scrapers.quaker import scrape_quaker
from scrapers.montessori import scrape_montessori
from scrapers.waldorf import scrape_waldorf
from scrapers.classical import scrape_classical
from scrapers.ib_schools import scrape_ib_schools
from scrapers.naeyc import scrape_naeyc
from scrapers.learning_diff import scrape_learning_diff
from scrapers.military import scrape_military

SCRAPERS = {
    'acsi': scrape_acsi,
    'catholic': scrape_catholic,
    'jewish': scrape_jewish,
    'episcopal': scrape_episcopal,
    'quaker': scrape_quaker,
    'montessori': scrape_montessori,
    'waldorf': scrape_waldorf,
    'classical': scrape_classical,
    'ib_schools': scrape_ib_schools,
    'naeyc': scrape_naeyc,
    'learning_diff': scrape_learning_diff,
    'military': scrape_military,
}

__all__ = ['SCRAPERS']
