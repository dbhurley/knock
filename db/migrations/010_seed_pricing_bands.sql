-- 010_seed_pricing_bands.sql
-- Insert the 7 pricing bands

INSERT INTO pricing_bands (band_code, band_name, salary_range_low, salary_range_high, fee_amount) VALUES
    ('band_a', 'Band A: Entry Executive',     70000,   100000,  20000),
    ('band_b', 'Band B: Mid Executive',       100001,  150000,  30000),
    ('band_c', 'Band C: Senior Executive',    150001,  200000,  40000),
    ('band_d', 'Band D: Head of School I',    200001,  275000,  55000),
    ('band_e', 'Band E: Head of School II',   275001,  375000,  75000),
    ('band_f', 'Band F: Head of School III',  375001,  500000, 100000),
    ('band_g', 'Band G: Elite',               500001, 9999999, 125000);
