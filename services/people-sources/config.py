"""
Configuration for all people source scrapers and importers.
Central registry of URLs, rate limits, and association metadata.
"""

# ---------------------------------------------------------------------------
# Global defaults
# ---------------------------------------------------------------------------

DEFAULT_RATE_LIMIT = 2.5          # seconds between requests
DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT = 30              # seconds
DEFAULT_USER_AGENT = 'Knock Research Bot (askknock.com; data-partnerships@askknock.com)'

# ---------------------------------------------------------------------------
# State / Regional Association Registry
# ---------------------------------------------------------------------------
# Each entry: short code -> metadata dict with:
#   name, url, directory_url(s), region, scrape_strategy, rate_limit
#
# scrape_strategy values:
#   'member_list'    - A single page/paginated list of member schools
#   'member_detail'  - Directory links to individual school pages
#   'api'            - JSON API available
#   'sitemap'        - Parse sitemap.xml to discover school pages
#   'manual'         - Requires manual CSV; auto-scraping blocked or infeasible

ASSOCIATION_REGISTRY = {
    'cais': {
        'name': 'California Association of Independent Schools',
        'short_name': 'CAIS',
        'url': 'https://www.caisca.org',
        'directory_urls': [
            'https://www.caisca.org/page/member-school-directory',
            'https://www.caisca.org/page/memberschooldirectory',
        ],
        'region': 'west',
        'states': ['CA'],
        'rate_limit': 3.0,
        'scrape_strategy': 'member_list',
    },
    'aisne': {
        'name': 'Association of Independent Schools in New England',
        'short_name': 'AISNE',
        'url': 'https://www.aisne.org',
        'directory_urls': [
            'https://www.aisne.org/school-directory',
            'https://www.aisne.org/schools',
        ],
        'region': 'northeast',
        'states': ['MA', 'CT', 'RI', 'NH', 'VT', 'ME'],
        'rate_limit': 3.0,
        'scrape_strategy': 'member_list',
    },
    'nysais': {
        'name': 'New York State Association of Independent Schools',
        'short_name': 'NYSAIS',
        'url': 'https://www.nysais.org',
        'directory_urls': [
            'https://www.nysais.org/member-schools',
            'https://nysais.org/school-directory',
        ],
        'region': 'northeast',
        'states': ['NY'],
        'rate_limit': 3.0,
        'scrape_strategy': 'member_list',
    },
    'isas': {
        'name': 'Independent Schools Association of the Southwest',
        'short_name': 'ISAS',
        'url': 'https://www.isasw.org',
        'directory_urls': [
            'https://www.isasw.org/member-schools',
            'https://www.isasw.org/school-directory',
        ],
        'region': 'southwest',
        'states': ['TX', 'NM', 'AZ', 'OK'],
        'rate_limit': 3.0,
        'scrape_strategy': 'member_list',
    },
    'aims': {
        'name': 'Association of Independent Maryland & DC Schools',
        'short_name': 'AIMS',
        'url': 'https://www.aimsmddc.org',
        'directory_urls': [
            'https://www.aimsmddc.org/member-schools',
            'https://www.aimsmddc.org/school-directory',
        ],
        'region': 'mid_atlantic',
        'states': ['MD', 'DC'],
        'rate_limit': 3.0,
        'scrape_strategy': 'member_list',
    },
    'pais': {
        'name': 'Pennsylvania Association of Independent Schools',
        'short_name': 'PAIS',
        'url': 'https://www.paispa.org',
        'directory_urls': [
            'https://www.paispa.org/member-schools',
            'https://paispa.org/school-directory',
        ],
        'region': 'mid_atlantic',
        'states': ['PA'],
        'rate_limit': 3.0,
        'scrape_strategy': 'member_list',
    },
    'fcis': {
        'name': 'Florida Council of Independent Schools',
        'short_name': 'FCIS',
        'url': 'https://www.fcis.org',
        'directory_urls': [
            'https://www.fcis.org/member-schools',
            'https://www.fcis.org/school-directory',
        ],
        'region': 'southeast',
        'states': ['FL'],
        'rate_limit': 3.0,
        'scrape_strategy': 'member_list',
    },
    'isboa': {
        'name': 'Independent School Business Officers Association',
        'short_name': 'ISBOA',
        'url': 'https://www.isboa.org',
        'directory_urls': [
            'https://www.isboa.org/members',
        ],
        'region': 'national',
        'states': [],
        'rate_limit': 3.0,
        'scrape_strategy': 'member_list',
    },
    'tabs': {
        'name': 'The Association of Boarding Schools',
        'short_name': 'TABS',
        'url': 'https://www.tabs.org',
        'directory_urls': [
            'https://www.tabs.org/school-search',
            'https://www.tabs.org/schools',
        ],
        'region': 'national',
        'states': [],
        'rate_limit': 3.0,
        'scrape_strategy': 'member_list',
    },
}

# ---------------------------------------------------------------------------
# NAIS Conference Sources
# ---------------------------------------------------------------------------

NAIS_CONFERENCE_SOURCES = {
    'annual_conference': {
        'name': 'NAIS Annual Conference',
        'base_url': 'https://www.nais.org/annual-conference',
        'speaker_urls': [
            'https://www.nais.org/annual-conference/speakers',
            'https://annualconference.nais.org/speakers',
        ],
        'schedule_urls': [
            'https://www.nais.org/annual-conference/schedule',
            'https://annualconference.nais.org/schedule',
        ],
        'event_type': 'conference',
    },
    'pocc': {
        'name': 'NAIS People of Color Conference (PoCC)',
        'base_url': 'https://www.nais.org/events/people-of-color-conference',
        'speaker_urls': [
            'https://pocc.nais.org/speakers',
            'https://www.nais.org/events/people-of-color-conference/speakers',
        ],
        'schedule_urls': [
            'https://pocc.nais.org/schedule',
        ],
        'event_type': 'conference',
    },
    'new_heads': {
        'name': 'NAIS Institute for New Heads',
        'base_url': 'https://www.nais.org/events/institute-for-new-heads',
        'speaker_urls': [
            'https://www.nais.org/events/institute-for-new-heads/faculty',
        ],
        'schedule_urls': [],
        'event_type': 'institute',
    },
}

# ---------------------------------------------------------------------------
# Education Publication Sources
# ---------------------------------------------------------------------------

PUBLICATION_SOURCES = {
    'nais_magazine': {
        'name': 'NAIS Independent School Magazine',
        'base_url': 'https://www.nais.org/magazine',
        'article_list_urls': [
            'https://www.nais.org/magazine/independent-school',
            'https://www.nais.org/learn/independent-school-magazine',
        ],
        'rss_url': None,
        'scrape_strategy': 'html',
        'rate_limit': 3.0,
    },
    'edweek': {
        'name': 'Education Week',
        'base_url': 'https://www.edweek.org',
        'article_list_urls': [
            'https://www.edweek.org/leadership',
        ],
        'rss_url': 'https://www.edweek.org/feed',
        'scrape_strategy': 'rss',
        'rate_limit': 3.0,
    },
    'edsurge': {
        'name': 'EdSurge',
        'base_url': 'https://www.edsurge.com',
        'article_list_urls': [
            'https://www.edsurge.com/news',
        ],
        'rss_url': 'https://www.edsurge.com/feeds/rss',
        'scrape_strategy': 'rss',
        'rate_limit': 3.0,
    },
}

# ---------------------------------------------------------------------------
# Podcast Sources
# ---------------------------------------------------------------------------

PODCAST_SOURCES = {
    'heads_together': {
        'name': 'Heads Together',
        'rss_urls': [
            'https://feeds.buzzsprout.com/headstogether.rss',
            'https://anchor.fm/s/headstogether/podcast/rss',
        ],
        'search_terms': ['Heads Together podcast independent school'],
        'itunes_search': 'Heads Together independent school',
    },
    'enrollment_mgmt': {
        'name': 'The Enrollment Management Podcast',
        'rss_urls': [
            'https://feeds.buzzsprout.com/enrollmentmanagement.rss',
        ],
        'search_terms': ['enrollment management podcast independent school'],
        'itunes_search': 'Enrollment Management independent school',
    },
    'independent_leadership': {
        'name': 'Independent School Leadership',
        'rss_urls': [],
        'search_terms': ['Independent School Leadership podcast'],
        'itunes_search': 'Independent School Leadership',
    },
    'school_leadership_series': {
        'name': 'The School Leadership Series',
        'rss_urls': [],
        'search_terms': ['School Leadership Series podcast'],
        'itunes_search': 'School Leadership Series',
    },
    'dreaming_in_color': {
        'name': 'Dreaming in Color',
        'rss_urls': [],
        'search_terms': ['Dreaming in Color podcast school leaders BIPOC'],
        'itunes_search': 'Dreaming in Color school leaders',
    },
}

# ---------------------------------------------------------------------------
# Job Board Sources
# ---------------------------------------------------------------------------

JOB_BOARD_SOURCES = {
    'nais_careers': {
        'name': 'NAIS Career Center',
        'base_url': 'https://careers.nais.org',
        'search_urls': [
            'https://careers.nais.org/jobs?keywords=head+of+school',
            'https://careers.nais.org/jobs?keywords=director',
        ],
        'rss_url': None,
        'rate_limit': 3.0,
    },
    'carney_sandoe': {
        'name': 'Carney Sandoe & Associates',
        'base_url': 'https://www.carneysandoe.com',
        'search_urls': [
            'https://www.carneysandoe.com/find-a-job',
            'https://www.carneysandoe.com/jobs',
        ],
        'rss_url': None,
        'rate_limit': 3.0,
    },
    'edsurge_jobs': {
        'name': 'EdSurge Jobs',
        'base_url': 'https://www.edsurge.com/jobs',
        'search_urls': [
            'https://www.edsurge.com/jobs?q=head+of+school',
        ],
        'rss_url': None,
        'rate_limit': 3.0,
    },
}

# ---------------------------------------------------------------------------
# University Ed Leadership Programs
# ---------------------------------------------------------------------------

UNIVERSITY_PROGRAMS = {
    'klingenstein': {
        'institution': 'Columbia University',
        'program_name': 'Klingenstein Center for Independent School Leadership',
        'degree_type': 'masters',
        'specialization': 'Independent School Leadership',
        'program_url': 'https://www.tc.columbia.edu/klingenstein/',
        'avg_cohort_size': 25,
        'typical_duration': '1 year',
        'program_format': 'full_time',
        'ranking_tier': 'top_10',
    },
    'harvard_eld': {
        'institution': 'Harvard Graduate School of Education',
        'program_name': 'Doctor of Education Leadership (Ed.L.D.)',
        'degree_type': 'ed_d',
        'specialization': 'Education Leadership',
        'program_url': 'https://www.gse.harvard.edu/eld',
        'avg_cohort_size': 25,
        'typical_duration': '3 years',
        'program_format': 'full_time',
        'ranking_tier': 'top_10',
    },
    'penn_gse': {
        'institution': 'University of Pennsylvania',
        'program_name': 'Penn GSE Mid-Career Doctoral Program',
        'degree_type': 'ed_d',
        'specialization': 'Educational Leadership',
        'program_url': 'https://www.gse.upenn.edu/',
        'avg_cohort_size': 30,
        'typical_duration': '3 years',
        'program_format': 'executive',
        'ranking_tier': 'top_10',
    },
    'vanderbilt': {
        'institution': 'Vanderbilt University',
        'program_name': 'Peabody College Ed.D. in Leadership and Policy',
        'degree_type': 'ed_d',
        'specialization': 'Leadership and Policy',
        'program_url': 'https://peabody.vanderbilt.edu/',
        'avg_cohort_size': 20,
        'typical_duration': '3 years',
        'program_format': 'full_time',
        'ranking_tier': 'top_10',
    },
    'stanford_gse': {
        'institution': 'Stanford University',
        'program_name': 'Stanford GSE Policy, Organization, and Leadership Studies',
        'degree_type': 'ph_d',
        'specialization': 'Education Leadership',
        'program_url': 'https://ed.stanford.edu/',
        'avg_cohort_size': 15,
        'typical_duration': '5 years',
        'program_format': 'full_time',
        'ranking_tier': 'top_10',
    },
    'penn_gel': {
        'institution': 'University of Pennsylvania',
        'program_name': 'GEL (Generations in Exec Leadership)',
        'degree_type': 'certificate',
        'specialization': 'Executive Leadership',
        'program_url': 'https://www.gse.upenn.edu/',
        'avg_cohort_size': 30,
        'typical_duration': '1 year',
        'program_format': 'executive',
        'ranking_tier': 'top_25',
    },
    'bank_street': {
        'institution': 'Bank Street College of Education',
        'program_name': 'Educational Leadership Program',
        'degree_type': 'masters',
        'specialization': 'Educational Leadership',
        'program_url': 'https://www.bankstreet.edu/',
        'avg_cohort_size': 20,
        'typical_duration': '2 years',
        'program_format': 'part_time',
        'ranking_tier': 'top_25',
    },
}

# ---------------------------------------------------------------------------
# ProPublica 990 API
# ---------------------------------------------------------------------------

PROPUBLICA_990_API = {
    'base_url': 'https://projects.propublica.org/nonprofits/api/v2',
    'org_endpoint': '/organizations/{ein}.json',
    'filing_endpoint': '/organizations/{ein}/filings/{tax_period}.json',
    'search_endpoint': '/search.json?q={query}&page={page}',
    'rate_limit': 1.0,  # Be extra polite to ProPublica
}

# ---------------------------------------------------------------------------
# iTunes Podcast Search API
# ---------------------------------------------------------------------------

ITUNES_SEARCH_API = 'https://itunes.apple.com/search'
