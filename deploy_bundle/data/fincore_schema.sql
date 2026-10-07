-- FinCore Enterprise migration 0001. PostgreSQL 17+. Apply to a NEW dedicated DB.
-- Analytics uses individual restricted LOGIN roles. Never use migration credentials.
BEGIN;
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['fincore_owner','fincore_compliance','fincore_branch','fincore_fraud'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
   IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r AND (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb)) THEN
    RAISE EXCEPTION 'Unsafe pre-existing FinCore role'; END IF;
  ELSE EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE',r); END IF;
 END LOOP;
END $$;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
DO $$ BEGIN EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database()); END $$;
CREATE SCHEMA fincore_crypto;
CREATE EXTENSION pgcrypto WITH SCHEMA fincore_crypto;
REVOKE ALL ON SCHEMA fincore_crypto FROM PUBLIC;
CREATE SCHEMA fincore AUTHORIZATION fincore_owner;
CREATE SCHEMA security AUTHORIZATION fincore_owner;
CREATE SCHEMA compliance AUTHORIZATION fincore_owner;
CREATE SCHEMA branch AUTHORIZATION fincore_owner;
CREATE SCHEMA fraud AUTHORIZATION fincore_owner;
SET LOCAL ROLE fincore_owner;
REVOKE ALL ON SCHEMA fincore, security, compliance, branch, fraud FROM PUBLIC;
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

CREATE TABLE fincore.schema_versions(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
INSERT INTO fincore.schema_versions VALUES ('0001', now());
CREATE TABLE fincore.institution_config(singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 business_timezone text NOT NULL CHECK(business_timezone IN ('Africa/Cairo','UTC','America/New_York')));
INSERT INTO fincore.institution_config VALUES(true,'Africa/Cairo');
CREATE FUNCTION fincore.business_date_at(instant timestamptz) RETURNS date LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS
 $$ SELECT (instant AT TIME ZONE business_timezone)::date FROM fincore.institution_config WHERE singleton $$;
CREATE FUNCTION fincore.business_date() RETURNS date LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS
 $$ SELECT fincore.business_date_at(statement_timestamp()) $$;
CREATE TABLE fincore.currencies(code char(3) PRIMARY KEY, minor_units smallint NOT NULL CHECK(minor_units=2));
INSERT INTO fincore.currencies VALUES ('USD',2),('EUR',2),('EGP',2);
CREATE TABLE fincore.branches(branch_id uuid PRIMARY KEY, branch_code text UNIQUE NOT NULL, country_code char(2) NOT NULL);
CREATE TABLE fincore.customers(
 customer_id uuid PRIMARY KEY, encrypted_identifier bytea NOT NULL CHECK(octet_length(encrypted_identifier)>28),
 identifier_key_ref text NOT NULL, identifier_algorithm text NOT NULL CHECK(identifier_algorithm IN ('AES-256-GCM','PGP-AES256')),
 jurisdiction char(2) NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE fincore.customer_profiles(
 customer_id uuid PRIMARY KEY REFERENCES fincore.customers, encrypted_profile bytea NOT NULL CHECK(octet_length(encrypted_profile)>28),
 profile_key_ref text NOT NULL, kyc_status text NOT NULL CHECK(kyc_status IN ('pending','verified','rejected','expired')),
 verified_at timestamptz, risk_tier text NOT NULL CHECK(risk_tier IN ('low','medium','high')),
 risk_score numeric(5,2) NOT NULL CHECK(risk_score BETWEEN 0 AND 100), assessed_at timestamptz NOT NULL DEFAULT now(),
 CHECK(kyc_status<>'verified' OR verified_at IS NOT NULL));
CREATE TABLE fincore.accounts(
 account_id uuid PRIMARY KEY, customer_id uuid REFERENCES fincore.customers, branch_id uuid NOT NULL REFERENCES fincore.branches,
 account_type text NOT NULL CHECK(account_type IN ('checking','savings','loan','settlement')),
 currency char(3) NOT NULL REFERENCES fincore.currencies,
 normal_side text NOT NULL CHECK(normal_side IN ('debit','credit')), status text NOT NULL CHECK(status IN ('open','closed')),
 UNIQUE(account_id,branch_id,currency), CHECK((account_type IN ('checking','savings') AND normal_side='credit') OR
 (account_type IN ('loan','settlement') AND normal_side='debit')));
CREATE TABLE fincore.transactions(
 transaction_id uuid PRIMARY KEY, account_id uuid NOT NULL, branch_id uuid NOT NULL, currency char(3) NOT NULL,
 amount numeric(20,2) NOT NULL CHECK(amount>0), direction text NOT NULL CHECK(direction IN ('in','out')),
 channel text NOT NULL CHECK(channel IN ('cash','transfer','card','internal')),
 business_date date NOT NULL, status text NOT NULL CHECK(status IN ('pending','posted','rejected')),
 reversal_of uuid UNIQUE REFERENCES fincore.transactions, flagged boolean NOT NULL DEFAULT false,
 FOREIGN KEY(account_id,branch_id,currency) REFERENCES fincore.accounts(account_id,branch_id,currency),
 CHECK(reversal_of IS NULL OR reversal_of<>transaction_id));
CREATE TABLE fincore.transaction_parties(
 transaction_id uuid NOT NULL REFERENCES fincore.transactions, customer_id uuid NOT NULL REFERENCES fincore.customers,
 party_role text NOT NULL CHECK(party_role IN ('conductor','beneficiary')), PRIMARY KEY(transaction_id,customer_id,party_role));
CREATE TABLE fincore.transaction_events(
 event_id uuid PRIMARY KEY, transaction_id uuid NOT NULL REFERENCES fincore.transactions,
 event_type text NOT NULL, event_time timestamptz NOT NULL DEFAULT now(), evidence jsonb NOT NULL DEFAULT '{}',
 CHECK(jsonb_typeof(evidence)='object'));
CREATE TABLE fincore.journal_entries(
 entry_id uuid PRIMARY KEY, branch_id uuid NOT NULL REFERENCES fincore.branches, currency char(3) NOT NULL REFERENCES fincore.currencies,
 business_date date NOT NULL, status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','posted')),
 transaction_id uuid REFERENCES fincore.transactions, reversal_of uuid UNIQUE REFERENCES fincore.journal_entries,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(entry_id,branch_id,currency), CHECK(reversal_of IS NULL OR reversal_of<>entry_id));
CREATE TABLE fincore.journal_lines(
 entry_id uuid NOT NULL, line_no integer NOT NULL CHECK(line_no>0), account_id uuid NOT NULL,
 branch_id uuid NOT NULL, currency char(3) NOT NULL, debit numeric(20,2) NOT NULL DEFAULT 0,
 credit numeric(20,2) NOT NULL DEFAULT 0, PRIMARY KEY(entry_id,line_no),
 CHECK((debit>0 AND credit=0) OR (credit>0 AND debit=0)),
 FOREIGN KEY(entry_id,branch_id,currency) REFERENCES fincore.journal_entries(entry_id,branch_id,currency),
 FOREIGN KEY(account_id,branch_id,currency) REFERENCES fincore.accounts(account_id,branch_id,currency));
CREATE TABLE fincore.account_holds(
 hold_id uuid PRIMARY KEY, account_id uuid NOT NULL REFERENCES fincore.accounts,
 amount numeric(20,2) NOT NULL CHECK(amount>0), placed_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 released_at timestamptz, CHECK(expires_at>placed_at), CHECK(released_at IS NULL OR released_at>=placed_at));
CREATE TABLE fincore.loans(
 loan_id uuid PRIMARY KEY, account_id uuid UNIQUE NOT NULL REFERENCES fincore.accounts,
 annual_rate numeric(10,8) NOT NULL CHECK(annual_rate BETWEEN 0 AND 1),
 day_count text NOT NULL CHECK(day_count IN ('ACT/360','ACT/365F','30E/360')), originated_on date NOT NULL, matures_on date NOT NULL,
 CHECK(matures_on>originated_on));
CREATE TABLE fincore.loan_installments(
 loan_id uuid NOT NULL REFERENCES fincore.loans, installment_no integer NOT NULL CHECK(installment_no>0),
 due_on date NOT NULL, scheduled_amount numeric(20,2) NOT NULL CHECK(scheduled_amount>0),
 paid_amount numeric(20,2) NOT NULL DEFAULT 0 CHECK(paid_amount>=0 AND paid_amount<=scheduled_amount),
 PRIMARY KEY(loan_id,installment_no));
CREATE TABLE fincore.compliance_cases(
 case_id uuid PRIMARY KEY, customer_id uuid NOT NULL REFERENCES fincore.customers,
 case_type text NOT NULL CHECK(case_type IN ('KYC','AML','SAR','CTR')), status text NOT NULL CHECK(status IN ('open','review','closed')),
 opened_at timestamptz NOT NULL DEFAULT now(), risk_score numeric(5,2) NOT NULL CHECK(risk_score BETWEEN 0 AND 100),
 confidential_evidence jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(confidential_evidence)='object'));
CREATE TABLE fincore.screening_hits(
 hit_id uuid PRIMARY KEY, customer_id uuid NOT NULL REFERENCES fincore.customers,
 case_id uuid NOT NULL REFERENCES fincore.compliance_cases, list_source text NOT NULL,
 match_score numeric(5,2) NOT NULL CHECK(match_score BETWEEN 0 AND 100),
 disposition text NOT NULL CHECK(disposition IN ('pending','confirmed','false_positive')), screened_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE fincore.investigation_cases(
 case_id uuid PRIMARY KEY, status text NOT NULL CHECK(status IN ('active','closed')),
 opened_at timestamptz NOT NULL DEFAULT now(), reason_code text NOT NULL);
CREATE TABLE fincore.case_transactions(case_id uuid NOT NULL REFERENCES fincore.investigation_cases,
 transaction_id uuid NOT NULL REFERENCES fincore.transactions, PRIMARY KEY(case_id,transaction_id));
CREATE TABLE fincore.card_events(
 event_id uuid PRIMARY KEY, transaction_id uuid NOT NULL REFERENCES fincore.transactions,
 card_token uuid NOT NULL, event_type text NOT NULL, event_time timestamptz NOT NULL DEFAULT now(), outcome text NOT NULL);
CREATE TABLE fincore.audit_logs(
 audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, event_time timestamptz NOT NULL DEFAULT now(),
 actor name NOT NULL DEFAULT session_user, action text NOT NULL, object_id uuid, evidence jsonb NOT NULL DEFAULT '{}');
CREATE TABLE security.principals(db_login name PRIMARY KEY, persona text NOT NULL CHECK(persona IN
 ('compliance_officer','branch_analyst','fraud_investigator')), enabled boolean NOT NULL DEFAULT true);
CREATE TABLE security.branch_assignments(db_login name NOT NULL REFERENCES security.principals,
 branch_id uuid NOT NULL REFERENCES fincore.branches, PRIMARY KEY(db_login,branch_id));
CREATE TABLE security.case_assignments(db_login name NOT NULL REFERENCES security.principals,
 case_id uuid NOT NULL REFERENCES fincore.investigation_cases, PRIMARY KEY(db_login,case_id));

CREATE FUNCTION security.persona() RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS
 $$ SELECT persona FROM security.principals WHERE db_login=session_user AND enabled $$;
CREATE FUNCTION security.has_branch(id uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS
 $$ SELECT EXISTS(SELECT 1 FROM security.branch_assignments a JOIN security.principals p USING(db_login)
 WHERE a.db_login=session_user AND p.enabled AND p.persona='branch_analyst' AND a.branch_id=id) $$;
CREATE FUNCTION security.has_case(id uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS
 $$ SELECT EXISTS(SELECT 1 FROM security.case_assignments a JOIN security.principals p USING(db_login)
 JOIN fincore.investigation_cases c USING(case_id) WHERE a.db_login=session_user AND p.enabled
 AND p.persona='fraud_investigator' AND c.status='active' AND a.case_id=id) $$;
CREATE FUNCTION security.has_transaction(id uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS
 $$ SELECT EXISTS(SELECT 1 FROM fincore.case_transactions ct WHERE ct.transaction_id=id AND security.has_case(ct.case_id)) $$;

CREATE FUNCTION fincore.check_balanced(id uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE e fincore.journal_entries; n integer; d numeric; c numeric;
BEGIN
 SELECT * INTO e FROM fincore.journal_entries WHERE entry_id=id;
 IF FOUND AND e.status='posted' THEN
  SELECT count(*),coalesce(sum(debit),0),coalesce(sum(credit),0) INTO n,d,c FROM fincore.journal_lines WHERE entry_id=id;
  IF n<2 OR d<>c THEN RAISE EXCEPTION 'LEDGER_UNBALANCED' USING ERRCODE='23514'; END IF;
  IF e.reversal_of IS NOT NULL AND EXISTS(
   SELECT 1 FROM
    (SELECT account_id,sum(debit) debit,sum(credit) credit FROM fincore.journal_lines
     WHERE entry_id=id GROUP BY account_id) reversal
    FULL JOIN (SELECT account_id,sum(debit) debit,sum(credit) credit FROM fincore.journal_lines
     WHERE entry_id=e.reversal_of GROUP BY account_id) original USING(account_id)
   WHERE coalesce(reversal.debit,0)<>coalesce(original.credit,0)
      OR coalesce(reversal.credit,0)<>coalesce(original.debit,0)
  ) THEN RAISE EXCEPTION 'LEDGER_REVERSAL_NOT_INVERSE' USING ERRCODE='23514'; END IF;
 END IF;
END $$;
CREATE FUNCTION fincore.guard_journal_line() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE s text;
BEGIN
 -- Lock every affected header in deterministic order before any line mutation.
 PERFORM 1 FROM fincore.journal_entries WHERE entry_id IN
 (CASE WHEN TG_OP<>'INSERT' THEN OLD.entry_id END, CASE WHEN TG_OP<>'DELETE' THEN NEW.entry_id END) ORDER BY entry_id FOR UPDATE;
 IF TG_OP<>'INSERT' THEN SELECT status INTO s FROM fincore.journal_entries WHERE entry_id=OLD.entry_id;
  IF s='posted' THEN RAISE EXCEPTION 'POSTED_LEDGER_IMMUTABLE' USING ERRCODE='23514'; END IF; END IF;
 IF TG_OP<>'DELETE' THEN SELECT status INTO s FROM fincore.journal_entries WHERE entry_id=NEW.entry_id;
  IF s='posted' THEN RAISE EXCEPTION 'POSTED_LEDGER_IMMUTABLE' USING ERRCODE='23514'; END IF; END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER journal_line_guard BEFORE INSERT OR UPDATE OR DELETE ON fincore.journal_lines FOR EACH ROW EXECUTE FUNCTION fincore.guard_journal_line();
CREATE FUNCTION fincore.guard_journal_entry() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP<>'INSERT' AND OLD.status='posted' THEN RAISE EXCEPTION 'POSTED_LEDGER_IMMUTABLE' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' AND NEW.status='posted' THEN RAISE EXCEPTION 'POST_IN_DRAFT_THEN_SEAL' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' AND NEW.status='posted' THEN
  IF NEW.branch_id<>OLD.branch_id OR NEW.currency<>OLD.currency OR NEW.entry_id<>OLD.entry_id THEN
   RAISE EXCEPTION 'LEDGER_IDENTITY_IMMUTABLE' USING ERRCODE='23514'; END IF;
  IF NEW.reversal_of IS NOT NULL AND NOT EXISTS(SELECT 1 FROM fincore.journal_entries original
    WHERE original.entry_id=NEW.reversal_of AND original.status='posted' AND original.currency=NEW.currency AND original.branch_id=NEW.branch_id) THEN
   RAISE EXCEPTION 'INVALID_LEDGER_REVERSAL' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER journal_entry_guard BEFORE INSERT OR UPDATE OR DELETE ON fincore.journal_entries FOR EACH ROW EXECUTE FUNCTION fincore.guard_journal_entry();
CREATE FUNCTION fincore.deferred_balance() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN PERFORM fincore.check_balanced(OLD.entry_id); END IF;
 IF TG_OP<>'DELETE' THEN PERFORM fincore.check_balanced(NEW.entry_id); END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER balance_entry AFTER INSERT OR UPDATE OR DELETE ON fincore.journal_entries
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fincore.deferred_balance();
CREATE CONSTRAINT TRIGGER balance_line AFTER INSERT OR UPDATE OR DELETE ON fincore.journal_lines
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fincore.deferred_balance();
CREATE FUNCTION fincore.posting_audit() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.status='posted' THEN INSERT INTO fincore.audit_logs(action,object_id,evidence)
 VALUES('LEDGER_POSTED',NEW.entry_id,jsonb_build_object('currency',NEW.currency,'reversal_of',NEW.reversal_of)); END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER posting_audit AFTER UPDATE OF status ON fincore.journal_entries FOR EACH ROW EXECUTE FUNCTION fincore.posting_audit();
CREATE FUNCTION fincore.audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'AUDIT_IMMUTABLE' USING ERRCODE='23514'; END $$;
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON fincore.audit_logs FOR EACH ROW EXECUTE FUNCTION fincore.audit_immutable();
CREATE FUNCTION fincore.day_count_fraction(a date,b date,basis text) RETURNS numeric LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
BEGIN
 IF b<a THEN RAISE EXCEPTION 'INVALID_ACCRUAL_PERIOD'; END IF;
 IF basis='ACT/360' THEN RETURN (b-a)::numeric/360;
 ELSIF basis='ACT/365F' THEN RETURN (b-a)::numeric/365;
 ELSIF basis='30E/360' THEN RETURN (360*(extract(year FROM b)-extract(year FROM a))+30*(extract(month FROM b)-extract(month FROM a))+
 least(30,extract(day FROM b))-least(30,extract(day FROM a)))/360;
 ELSE RAISE EXCEPTION 'UNREGISTERED_DAY_COUNT'; END IF;
END $$;

-- FORCE RLS includes the owner; only an explicit internal maintenance policy permits it.
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['customers','customer_profiles','accounts','transactions','transaction_parties','transaction_events',
 'journal_entries','journal_lines','account_holds','loans','loan_installments','compliance_cases','screening_hits',
 'investigation_cases','case_transactions','card_events','audit_logs'] LOOP
  EXECUTE format('ALTER TABLE fincore.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE fincore.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY internal_maintenance ON fincore.%I TO fincore_owner USING(true) WITH CHECK(true)',t);
 END LOOP;
END $$;
CREATE POLICY compliance_customers ON fincore.customers FOR SELECT TO fincore_compliance USING(security.persona()='compliance_officer');
CREATE POLICY compliance_profiles ON fincore.customer_profiles FOR SELECT TO fincore_compliance USING(security.persona()='compliance_officer');
CREATE POLICY compliance_transactions ON fincore.transactions FOR SELECT TO fincore_compliance USING(security.persona()='compliance_officer');
CREATE POLICY compliance_parties ON fincore.transaction_parties FOR SELECT TO fincore_compliance USING(security.persona()='compliance_officer');
CREATE POLICY compliance_cases ON fincore.compliance_cases FOR SELECT TO fincore_compliance USING(security.persona()='compliance_officer');
CREATE POLICY compliance_screening ON fincore.screening_hits FOR SELECT TO fincore_compliance USING(security.persona()='compliance_officer');
CREATE POLICY branch_accounts ON fincore.accounts FOR SELECT TO fincore_branch USING(security.has_branch(branch_id));
CREATE POLICY branch_transactions ON fincore.transactions FOR SELECT TO fincore_branch USING(security.has_branch(branch_id));
CREATE POLICY branch_entries ON fincore.journal_entries FOR SELECT TO fincore_branch USING(security.has_branch(branch_id));
CREATE POLICY branch_lines ON fincore.journal_lines FOR SELECT TO fincore_branch USING(security.has_branch(branch_id));
CREATE POLICY branch_holds ON fincore.account_holds FOR SELECT TO fincore_branch USING(EXISTS(SELECT 1 FROM fincore.accounts a WHERE a.account_id=account_holds.account_id));
CREATE POLICY branch_loans ON fincore.loans FOR SELECT TO fincore_branch USING(EXISTS(SELECT 1 FROM fincore.accounts a WHERE a.account_id=loans.account_id));
CREATE POLICY branch_installments ON fincore.loan_installments FOR SELECT TO fincore_branch USING(EXISTS(SELECT 1 FROM fincore.loans l WHERE l.loan_id=loan_installments.loan_id));
CREATE POLICY fraud_transactions ON fincore.transactions FOR SELECT TO fincore_fraud USING(flagged AND security.has_transaction(transaction_id));
CREATE POLICY fraud_cases ON fincore.investigation_cases FOR SELECT TO fincore_fraud USING(status='active' AND security.has_case(case_id));
CREATE POLICY fraud_links ON fincore.case_transactions FOR SELECT TO fincore_fraud USING(security.has_case(case_id));
CREATE POLICY fraud_events ON fincore.card_events FOR SELECT TO fincore_fraud USING(EXISTS(SELECT 1 FROM fincore.transactions t WHERE t.transaction_id=card_events.transaction_id));

GRANT USAGE ON SCHEMA security TO fincore_compliance,fincore_branch,fincore_fraud;
GRANT EXECUTE ON FUNCTION security.persona(),security.has_branch(uuid),security.has_case(uuid),security.has_transaction(uuid) TO fincore_compliance,fincore_branch,fincore_fraud;
GRANT USAGE ON SCHEMA fincore TO fincore_compliance,fincore_branch,fincore_fraud;
GRANT USAGE ON SCHEMA compliance TO fincore_compliance;
GRANT USAGE ON SCHEMA branch TO fincore_branch;
GRANT USAGE ON SCHEMA fraud TO fincore_fraud;
-- Column grants are independent of RLS: ciphertext, customer linkage and raw case evidence stay private.
GRANT SELECT(customer_id,jurisdiction) ON fincore.customers TO fincore_compliance;
GRANT SELECT(customer_id,kyc_status,verified_at,risk_tier,risk_score,assessed_at) ON fincore.customer_profiles TO fincore_compliance;
GRANT SELECT(transaction_id,account_id,branch_id,currency,amount,direction,channel,business_date,status,reversal_of,flagged) ON fincore.transactions TO fincore_compliance;
GRANT SELECT(transaction_id,customer_id,party_role) ON fincore.transaction_parties TO fincore_compliance;
GRANT SELECT(case_id,customer_id,case_type,status,opened_at,risk_score) ON fincore.compliance_cases TO fincore_compliance;
GRANT SELECT(hit_id,customer_id,case_id,list_source,match_score,disposition,screened_at) ON fincore.screening_hits TO fincore_compliance;
GRANT SELECT(account_id,branch_id,account_type,currency,normal_side,status) ON fincore.accounts TO fincore_branch;
GRANT SELECT(branch_id,business_date,currency,direction,amount,status,transaction_id) ON fincore.transactions TO fincore_branch;
GRANT SELECT(entry_id,branch_id,currency,business_date,status) ON fincore.journal_entries TO fincore_branch;
GRANT SELECT(entry_id,account_id,branch_id,currency,debit,credit) ON fincore.journal_lines TO fincore_branch;
GRANT SELECT(account_id,amount,placed_at,expires_at,released_at) ON fincore.account_holds TO fincore_branch;
GRANT SELECT(loan_id,account_id,annual_rate,day_count,originated_on,matures_on) ON fincore.loans TO fincore_branch;
GRANT SELECT(loan_id,due_on,scheduled_amount,paid_amount) ON fincore.loan_installments TO fincore_branch;
GRANT EXECUTE ON FUNCTION fincore.day_count_fraction(date,date,text) TO fincore_branch;
GRANT EXECUTE ON FUNCTION fincore.business_date(),fincore.business_date_at(timestamptz) TO fincore_branch;
GRANT SELECT(transaction_id,branch_id,business_date,currency,amount,direction,channel,flagged,status) ON fincore.transactions TO fincore_fraud;
GRANT SELECT(case_id,status,opened_at,reason_code) ON fincore.investigation_cases TO fincore_fraud;
GRANT SELECT(case_id,transaction_id) ON fincore.case_transactions TO fincore_fraud;
GRANT SELECT(event_id,transaction_id,card_token,event_type,event_time,outcome) ON fincore.card_events TO fincore_fraud;

CREATE VIEW compliance.kyc_reviews WITH(security_invoker=true,security_barrier=true) AS
 SELECT c.customer_id,c.jurisdiction,p.kyc_status,p.verified_at,p.risk_tier FROM fincore.customers c JOIN fincore.customer_profiles p USING(customer_id);
CREATE VIEW compliance.aml_transactions WITH(security_invoker=true,security_barrier=true) AS
 SELECT DISTINCT t.transaction_id,p.customer_id,t.branch_id,t.business_date,t.currency,t.amount,t.direction,t.channel,t.reversal_of,t.flagged
 FROM fincore.transactions t JOIN fincore.transaction_parties p USING(transaction_id) WHERE t.status='posted';
CREATE VIEW compliance.risk_assessments WITH(security_invoker=true,security_barrier=true) AS
 SELECT customer_id,risk_tier,risk_score,assessed_at FROM fincore.customer_profiles;
CREATE VIEW compliance.compliance_cases WITH(security_invoker=true,security_barrier=true) AS
 SELECT case_id,customer_id,case_type,status,opened_at,risk_score FROM fincore.compliance_cases;
CREATE VIEW compliance.screening_hits WITH(security_invoker=true,security_barrier=true) AS
 SELECT hit_id,customer_id,case_id,list_source,match_score,disposition,screened_at FROM fincore.screening_hits;
CREATE VIEW compliance.cash_daily_monitoring WITH(security_invoker=true,security_barrier=true) AS
 WITH movements AS(SELECT DISTINCT t.transaction_id,p.customer_id,t.business_date,t.amount,t.direction
 FROM fincore.transactions t JOIN fincore.transaction_parties p USING(transaction_id)
 JOIN fincore.customers c USING(customer_id) WHERE t.status='posted' AND t.channel='cash' AND t.currency='USD' AND c.jurisdiction='US'),
 totals AS(SELECT customer_id,business_date,sum(CASE WHEN direction='in' THEN amount ELSE 0 END) cash_in_usd,
 sum(CASE WHEN direction='out' THEN amount ELSE 0 END) cash_out_usd FROM movements GROUP BY customer_id,business_date)
 SELECT customer_id,business_date,cash_in_usd,cash_out_usd,10000.00::numeric threshold_usd,
 cash_in_usd>10000 OR cash_out_usd>10000 requires_review,'1.0.0'::text metric_version FROM totals;
CREATE VIEW branch.account_summaries WITH(security_invoker=true,security_barrier=true) AS
 WITH balances AS(SELECT l.account_id,sum(l.debit-l.credit) debit_balance FROM fincore.journal_lines l
 JOIN fincore.journal_entries e USING(entry_id) WHERE e.status='posted' AND e.business_date<=fincore.business_date() GROUP BY l.account_id),
 holds AS(SELECT account_id,sum(amount) held FROM fincore.account_holds WHERE placed_at<=statement_timestamp()
 AND expires_at>statement_timestamp() AND (released_at IS NULL OR released_at>statement_timestamp()) GROUP BY account_id)
 SELECT a.account_id,a.branch_id,a.account_type,a.currency,fincore.business_date() business_date,
 (CASE WHEN a.normal_side='debit' THEN 1 ELSE -1 END)*coalesce(b.debit_balance,0) posted_balance,
 coalesce(h.held,0) active_holds,(CASE WHEN a.normal_side='debit' THEN 1 ELSE -1 END)*coalesce(b.debit_balance,0)-coalesce(h.held,0) available_balance,
 '1.0.0'::text metric_version FROM fincore.accounts a LEFT JOIN balances b USING(account_id) LEFT JOIN holds h USING(account_id) WHERE a.status='open';
CREATE VIEW branch.daily_flows WITH(security_invoker=true,security_barrier=true) AS
 SELECT branch_id,business_date,currency,direction,count(*) transaction_count,sum(amount) total_amount
 FROM fincore.transactions WHERE status='posted' GROUP BY branch_id,business_date,currency,direction;
CREATE VIEW branch.loan_performance WITH(security_invoker=true,security_barrier=true) AS
 WITH delinquency AS(SELECT loan_id,fincore.business_date()-min(due_on) overdue FROM fincore.loan_installments
 WHERE due_on<fincore.business_date() AND paid_amount<scheduled_amount GROUP BY loan_id)
 SELECT l.loan_id,l.account_id,a.branch_id,a.currency,a.posted_balance principal_outstanding,l.annual_rate,l.day_count,
 coalesce(d.overdue,0) days_past_due,a.posted_balance*l.annual_rate*fincore.day_count_fraction(fincore.business_date(),fincore.business_date()+1,l.day_count) daily_interest,
 '1.0.0'::text metric_version FROM fincore.loans l JOIN branch.account_summaries a USING(account_id) LEFT JOIN delinquency d USING(loan_id) WHERE a.account_type='loan';
CREATE VIEW fraud.flagged_transactions WITH(security_invoker=true,security_barrier=true) AS
 SELECT t.transaction_id,c.case_id,t.branch_id,t.business_date,t.currency,t.amount,t.direction,t.channel,t.flagged
 FROM fincore.transactions t JOIN fincore.case_transactions c USING(transaction_id)
 JOIN fincore.investigation_cases i USING(case_id) WHERE t.flagged AND i.status='active';
CREATE VIEW fraud.card_events WITH(security_invoker=true,security_barrier=true) AS
 SELECT e.event_id,t.case_id,e.transaction_id,e.card_token,e.event_type,e.event_time,e.outcome
 FROM fincore.card_events e JOIN fraud.flagged_transactions t USING(transaction_id);
CREATE VIEW fraud.investigation_cases WITH(security_invoker=true,security_barrier=true) AS
 SELECT case_id,status,opened_at,reason_code FROM fincore.investigation_cases WHERE status='active';
GRANT SELECT ON ALL TABLES IN SCHEMA compliance TO fincore_compliance;
GRANT SELECT ON ALL TABLES IN SCHEMA branch TO fincore_branch;
GRANT SELECT ON ALL TABLES IN SCHEMA fraud TO fincore_fraud;
CREATE INDEX transactions_business_day ON fincore.transactions(business_date,currency,channel,status);
CREATE INDEX accounts_branch ON fincore.accounts(branch_id);
CREATE INDEX journal_lines_account ON fincore.journal_lines(account_id);
CREATE INDEX journal_entries_business_day ON fincore.journal_entries(business_date) WHERE status='posted';
CREATE INDEX case_transactions_transaction ON fincore.case_transactions(transaction_id);
COMMIT;
