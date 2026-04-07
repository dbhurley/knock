-- enrich-05-school-segments.sql
-- Populates school_segment and pedagogy from religious_affiliation and name patterns.
-- The NCES religious_affiliation field is unreliable (~50% are mis-coded as
-- "Seventh-Day Adventist" by default), so we trust school name patterns first.
--
-- Run after migration 013_school_segments.sql

BEGIN;

UPDATE schools SET school_segment = NULL, pedagogy = NULL;

-- Pedagogy (style, not religion)
UPDATE schools SET pedagogy = 'montessori' WHERE name ILIKE '%montessori%' OR religious_affiliation = 'Montessori';
UPDATE schools SET pedagogy = 'waldorf'    WHERE name ILIKE '%waldorf%' OR name ILIKE '%steiner%';
UPDATE schools SET pedagogy = 'ib_world'   WHERE religious_affiliation = 'IB' OR name ILIKE '%international baccalaureate%';
UPDATE schools SET pedagogy = 'classical'  WHERE name ILIKE '%classical%' OR name ILIKE '%great hearts%';
UPDATE schools SET pedagogy = 'reggio'     WHERE name ILIKE '%reggio%';
UPDATE schools SET pedagogy = 'progressive' WHERE pedagogy IS NULL AND (name ILIKE '%progressive%' OR religious_affiliation = 'Friends');

-- Religious segments — name pattern matching first (most reliable)
UPDATE schools SET school_segment = 'catholic'
WHERE religious_affiliation IN ('Roman Catholic','Catholic')
   OR name ILIKE '%catholic%' OR name ILIKE '%saint %' OR name ILIKE '%st. %'
   OR name ILIKE '%diocese%' OR name ILIKE '%jesuit%' OR name ILIKE '%parochial%';

UPDATE schools SET school_segment = 'episcopal'
WHERE school_segment IS NULL
  AND (religious_affiliation = 'Episcopal' OR name ILIKE '%episcopal%' OR name ILIKE '%anglican%');

UPDATE schools SET school_segment = 'quaker'
WHERE school_segment IS NULL
  AND (religious_affiliation IN ('Friends','Quaker') OR name ILIKE '%friends school%' OR name ILIKE '%friends academy%' OR name ILIKE '%quaker%');

UPDATE schools SET school_segment = 'jewish'
WHERE school_segment IS NULL
  AND (religious_affiliation = 'Jewish' OR name ILIKE '%jewish%' OR name ILIKE '%hebrew%' OR name ILIKE '%yeshiva%' OR name ILIKE '%torah%' OR name ILIKE '%chabad%');

UPDATE schools SET school_segment = 'islamic'
WHERE school_segment IS NULL
  AND (religious_affiliation = 'Islamic' OR name ILIKE '%islamic%' OR name ILIKE '%muslim%' OR name ILIKE '%al-%academy%');

UPDATE schools SET school_segment = 'baptist'
WHERE school_segment IS NULL AND (religious_affiliation ILIKE '%Baptist%' OR name ILIKE '%baptist%');

UPDATE schools SET school_segment = 'lutheran'
WHERE school_segment IS NULL AND (religious_affiliation ILIKE '%Lutheran%' OR name ILIKE '%lutheran%');

UPDATE schools SET school_segment = 'methodist'
WHERE school_segment IS NULL AND (religious_affiliation ILIKE '%Methodist%' OR name ILIKE '%methodist%' OR name ILIKE '%wesleyan%');

UPDATE schools SET school_segment = 'presbyterian'
WHERE school_segment IS NULL AND (religious_affiliation ILIKE '%Presbyterian%' OR name ILIKE '%presbyterian%');

UPDATE schools SET school_segment = 'adventist'
WHERE school_segment IS NULL AND (name ILIKE '%adventist%' OR name ILIKE '%sda %');

UPDATE schools SET school_segment = 'lds'
WHERE school_segment IS NULL AND (religious_affiliation ILIKE '%Latter Day Saints%' OR name ILIKE '%latter-day%');

UPDATE schools SET school_segment = 'anabaptist'
WHERE school_segment IS NULL AND (religious_affiliation IN ('Mennonite','Amish','Brethren') OR name ILIKE '%mennonite%' OR name ILIKE '%amish%' OR name ILIKE '%brethren%');

UPDATE schools SET school_segment = 'pentecostal'
WHERE school_segment IS NULL AND (religious_affiliation IN ('Pentecostal','Assembly of God','Church of God in Christ') OR name ILIKE '%pentecostal%' OR name ILIKE '%assembly of god%');

UPDATE schools SET school_segment = 'orthodox_christian'
WHERE school_segment IS NULL AND (name ILIKE '%greek orthodox%' OR name ILIKE '%orthodox christian%' OR name ILIKE '%antiochian%');

UPDATE schools SET school_segment = 'evangelical_christian'
WHERE school_segment IS NULL
  AND (religious_affiliation IN ('Christian','Christian (unspecified)','Calvinist','Conservative Christian','Other Religious','Church of Christ','Church of God','Church of the Nazarene','Disciples of Christ','Evangelical Lutheran Church in America')
       OR name ILIKE '%christian academy%' OR name ILIKE '%christian school%' OR name ILIKE '%bible%');

-- Default to secular (the NCES religious_affiliation default is unreliable)
UPDATE schools SET school_segment = 'secular' WHERE school_segment IS NULL;

-- Report
SELECT school_segment, COUNT(*) FROM schools GROUP BY 1 ORDER BY 2 DESC;

COMMIT;
