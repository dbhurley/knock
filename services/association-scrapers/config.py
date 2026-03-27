"""
Configuration for Knock association scrapers.
URL registry, rate limits, user agents, and association metadata.
"""

# ---------------------------------------------------------------------------
# HTTP defaults
# ---------------------------------------------------------------------------

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Polite scraping: seconds between requests to the same domain
DEFAULT_REQUEST_DELAY = 2.5  # seconds
MAX_RETRIES = 3
BACKOFF_FACTOR = 2.0
REQUEST_TIMEOUT = 30  # seconds

# ---------------------------------------------------------------------------
# Association registry
# ---------------------------------------------------------------------------

ASSOCIATIONS = {
    "acsi": {
        "name": "Association of Christian Schools International",
        "short_name": "ACSI",
        "base_url": "https://www.acsi.org",
        "search_url": "https://www.acsi.org/school-search",
        "api_url": "https://www.acsi.org/api/school-search",
        "estimated_schools": 2400,
        "affiliation": "Christian",
        "accreditation_body": "ACSI",
        "tags": ["christian", "acsi", "private", "religious"],
        "request_delay": 3.0,
    },
    "catholic": {
        "name": "National Catholic Educational Association",
        "short_name": "NCEA",
        "base_url": "https://www.ncea.org",
        "search_url": "https://www.ncea.org/NCEA/Proclaim/Catholic_School_Data/NCEA/Proclaim/Catholic_School_Data/Catholic_School_Data.aspx",
        "directory_url": "https://www.privateschoolreview.com/catholic",
        "estimated_schools": 5900,
        "affiliation": "Catholic",
        "accreditation_body": "NCEA",
        "tags": ["catholic", "ncea", "private", "religious"],
        "request_delay": 3.0,
    },
    "jewish": {
        "name": "Prizmah: Center for Jewish Day Schools",
        "short_name": "Prizmah",
        "base_url": "https://www.prizmah.org",
        "search_url": "https://www.prizmah.org/jewish-day-school-directory",
        "directory_url": "https://www.prizmah.org/directory",
        "estimated_schools": 300,
        "affiliation": "Jewish",
        "accreditation_body": "Prizmah",
        "tags": ["jewish", "prizmah", "private", "religious", "day school"],
        "request_delay": 3.0,
    },
    "episcopal": {
        "name": "National Association of Episcopal Schools",
        "short_name": "NAES",
        "base_url": "https://www.episcopalschools.org",
        "search_url": "https://www.episcopalschools.org/school-directory/",
        "directory_url": "https://www.episcopalschools.org/school-directory/",
        "estimated_schools": 1100,
        "affiliation": "Episcopal",
        "accreditation_body": "NAES",
        "tags": ["episcopal", "naes", "private", "religious", "anglican"],
        "request_delay": 3.0,
    },
    "quaker": {
        "name": "Friends Council on Education",
        "short_name": "FCE",
        "base_url": "https://www.friendscouncil.org",
        "search_url": "https://www.friendscouncil.org/find-a-friends-school",
        "directory_url": "https://www.friendscouncil.org/find-a-friends-school",
        "estimated_schools": 80,
        "affiliation": "Quaker",
        "accreditation_body": "FCE",
        "tags": ["quaker", "friends", "fce", "private", "religious"],
        "request_delay": 3.0,
    },
    "montessori": {
        "name": "American Montessori Society",
        "short_name": "AMS",
        "base_url": "https://amshq.org",
        "search_url": "https://amshq.org/School-Resources/Find-a-School",
        "api_url": "https://amshq.org/api/schoolSearch",
        "ami_url": "https://amiusa.org/find-a-school/",
        "estimated_schools": 1300,
        "affiliation": "Montessori",
        "accreditation_body": "AMS",
        "tags": ["montessori", "ams", "private", "progressive"],
        "request_delay": 3.0,
    },
    "waldorf": {
        "name": "Association of Waldorf Schools of North America",
        "short_name": "AWSNA",
        "base_url": "https://www.waldorfeducation.org",
        "search_url": "https://www.waldorfeducation.org/waldorf-education/find-a-school",
        "directory_url": "https://www.waldorfeducation.org/find-a-school",
        "estimated_schools": 160,
        "affiliation": "Waldorf",
        "accreditation_body": "AWSNA",
        "tags": ["waldorf", "steiner", "awsna", "private", "progressive"],
        "request_delay": 3.0,
    },
    "classical": {
        "name": "Association of Classical Christian Schools",
        "short_name": "ACCS",
        "base_url": "https://classicalchristian.org",
        "search_url": "https://classicalchristian.org/find-a-school/",
        "directory_url": "https://classicalchristian.org/school-directory/",
        "estimated_schools": 500,
        "affiliation": "Classical Christian",
        "accreditation_body": "ACCS",
        "tags": ["classical", "christian", "accs", "private", "religious", "liberal arts"],
        "request_delay": 3.0,
    },
    "ib_schools": {
        "name": "International Baccalaureate Organization",
        "short_name": "IBO",
        "base_url": "https://www.ibo.org",
        "search_url": "https://www.ibo.org/programmes/find-an-ib-school/",
        "api_url": "https://www.ibo.org/wp-json/ibo/v1/schools",
        "estimated_schools": 2000,
        "affiliation": "IB",
        "accreditation_body": "IBO",
        "tags": ["ib", "international baccalaureate", "private", "college prep"],
        "request_delay": 3.0,
    },
    "naeyc": {
        "name": "National Association for the Education of Young Children",
        "short_name": "NAEYC",
        "base_url": "https://www.naeyc.org",
        "search_url": "https://www.naeyc.org/accreditation/search",
        "api_url": "https://www.naeyc.org/api/accreditation/search",
        "estimated_schools": 6500,
        "affiliation": "Early Childhood",
        "accreditation_body": "NAEYC",
        "tags": ["naeyc", "early childhood", "preschool", "daycare", "accredited"],
        "request_delay": 3.0,
    },
    "learning_diff": {
        "name": "NAPSEC / Learning Differences Schools",
        "short_name": "NAPSEC",
        "base_url": "https://www.napsec.org",
        "search_url": "https://www.napsec.org/members",
        "directory_url": "https://www.napsec.org/member-directory",
        "alt_url": "https://www.smart-kids.org/school-directory",
        "estimated_schools": 400,
        "affiliation": "Special Education",
        "accreditation_body": "NAPSEC",
        "tags": ["learning differences", "special education", "napsec", "private"],
        "request_delay": 3.0,
    },
    "military": {
        "name": "Association of Military Colleges and Schools of the United States",
        "short_name": "AMCSUS",
        "base_url": "https://amcsus.org",
        "search_url": "https://amcsus.org/member-schools/",
        "directory_url": "https://amcsus.org/member-schools/",
        "estimated_schools": 30,
        "affiliation": "Military",
        "accreditation_body": "AMCSUS",
        "tags": ["military", "amcsus", "private", "boarding", "college prep"],
        "request_delay": 3.0,
    },
}

# Mapping of scraper key -> module name (for dynamic import in run_all)
SCRAPER_MODULES = {
    "acsi": "scrapers.acsi",
    "catholic": "scrapers.catholic",
    "jewish": "scrapers.jewish",
    "episcopal": "scrapers.episcopal",
    "quaker": "scrapers.quaker",
    "montessori": "scrapers.montessori",
    "waldorf": "scrapers.waldorf",
    "classical": "scrapers.classical",
    "ib_schools": "scrapers.ib_schools",
    "naeyc": "scrapers.naeyc",
    "learning_diff": "scrapers.learning_diff",
    "military": "scrapers.military",
}

# US state name -> abbreviation mapping (for normalizing state data)
US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}

# Reverse mapping
STATE_ABBREVS = {v: v for v in US_STATES.values()}
STATE_ABBREVS.update({name: abbr for name, abbr in US_STATES.items()})
