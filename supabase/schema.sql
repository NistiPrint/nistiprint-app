


SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


CREATE SCHEMA IF NOT EXISTS "auth";


ALTER SCHEMA "auth" OWNER TO "supabase_admin";


CREATE SCHEMA IF NOT EXISTS "public";


ALTER SCHEMA "public" OWNER TO "pg_database_owner";


COMMENT ON SCHEMA "public" IS 'standard public schema';



CREATE SCHEMA IF NOT EXISTS "storage";


ALTER SCHEMA "storage" OWNER TO "supabase_admin";


CREATE TYPE "auth"."aal_level" AS ENUM (
    'aal1',
    'aal2',
    'aal3'
);


ALTER TYPE "auth"."aal_level" OWNER TO "supabase_auth_admin";


CREATE TYPE "auth"."code_challenge_method" AS ENUM (
    's256',
    'plain'
);


ALTER TYPE "auth"."code_challenge_method" OWNER TO "supabase_auth_admin";


CREATE TYPE "auth"."factor_status" AS ENUM (
    'unverified',
    'verified'
);


ALTER TYPE "auth"."factor_status" OWNER TO "supabase_auth_admin";


CREATE TYPE "auth"."factor_type" AS ENUM (
    'totp',
    'webauthn',
    'phone'
);


ALTER TYPE "auth"."factor_type" OWNER TO "supabase_auth_admin";


CREATE TYPE "auth"."oauth_authorization_status" AS ENUM (
    'pending',
    'approved',
    'denied',
    'expired'
);


ALTER TYPE "auth"."oauth_authorization_status" OWNER TO "supabase_auth_admin";


CREATE TYPE "auth"."oauth_client_type" AS ENUM (
    'public',
    'confidential'
);


ALTER TYPE "auth"."oauth_client_type" OWNER TO "supabase_auth_admin";


CREATE TYPE "auth"."oauth_registration_type" AS ENUM (
    'dynamic',
    'manual'
);


ALTER TYPE "auth"."oauth_registration_type" OWNER TO "supabase_auth_admin";


CREATE TYPE "auth"."oauth_response_type" AS ENUM (
    'code'
);


ALTER TYPE "auth"."oauth_response_type" OWNER TO "supabase_auth_admin";


CREATE TYPE "auth"."one_time_token_type" AS ENUM (
    'confirmation_token',
    'reauthentication_token',
    'recovery_token',
    'email_change_token_new',
    'email_change_token_current',
    'phone_change_token'
);


ALTER TYPE "auth"."one_time_token_type" OWNER TO "supabase_auth_admin";


CREATE TYPE "storage"."buckettype" AS ENUM (
    'STANDARD',
    'ANALYTICS',
    'VECTOR'
);


ALTER TYPE "storage"."buckettype" OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "auth"."email"() RETURNS "text"
    LANGUAGE "sql" STABLE
    AS $$
  select 
  coalesce(
    nullif(current_setting('request.jwt.claim.email', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'email')
  )::text
$$;


ALTER FUNCTION "auth"."email"() OWNER TO "supabase_auth_admin";


COMMENT ON FUNCTION "auth"."email"() IS 'Deprecated. Use auth.jwt() -> ''email'' instead.';



CREATE OR REPLACE FUNCTION "auth"."jwt"() RETURNS "jsonb"
    LANGUAGE "sql" STABLE
    AS $$
  select 
    coalesce(
        nullif(current_setting('request.jwt.claim', true), ''),
        nullif(current_setting('request.jwt.claims', true), '')
    )::jsonb
$$;


ALTER FUNCTION "auth"."jwt"() OWNER TO "supabase_auth_admin";


CREATE OR REPLACE FUNCTION "auth"."role"() RETURNS "text"
    LANGUAGE "sql" STABLE
    AS $$
  select 
  coalesce(
    nullif(current_setting('request.jwt.claim.role', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role')
  )::text
$$;


ALTER FUNCTION "auth"."role"() OWNER TO "supabase_auth_admin";


COMMENT ON FUNCTION "auth"."role"() IS 'Deprecated. Use auth.jwt() -> ''role'' instead.';



CREATE OR REPLACE FUNCTION "auth"."uid"() RETURNS "uuid"
    LANGUAGE "sql" STABLE
    AS $$
  select 
  coalesce(
    nullif(current_setting('request.jwt.claim.sub', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
  )::uuid
$$;


ALTER FUNCTION "auth"."uid"() OWNER TO "supabase_auth_admin";


COMMENT ON FUNCTION "auth"."uid"() IS 'Deprecated. Use auth.jwt() -> ''sub'' instead.';



CREATE OR REPLACE FUNCTION "public"."handle_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  -- 1. Try to update 'updated_at' (New Standard)
  BEGIN
    NEW.updated_at = now();
  EXCEPTION WHEN undefined_column THEN
    -- Ignore if column doesn't exist
  END;

  -- 2. Try to update 'atualizado_em' (Legacy Fallback)
  BEGIN
    NEW.atualizado_em = now();
  EXCEPTION WHEN undefined_column THEN
    -- Ignore if column doesn't exist
  END;
  
  RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."handle_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."standardize_table_timestamps"("target_table" "text") RETURNS "void"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    -- Check if table exists first
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = target_table) THEN
        RAISE NOTICE 'Table % does not exist, skipping.', target_table;
        RETURN;
    END IF;

    -- Add created_at if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = target_table AND column_name = 'created_at') THEN
        EXECUTE format('ALTER TABLE public.%I ADD COLUMN created_at TIMESTAMPTZ DEFAULT now()', target_table);
    END IF;

    -- Add updated_at if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = target_table AND column_name = 'updated_at') THEN
        EXECUTE format('ALTER TABLE public.%I ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now()', target_table);
    END IF;

    -- Sync from legacy 'atualizado_em' if it exists
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = target_table AND column_name = 'atualizado_em') THEN
        EXECUTE format('UPDATE public.%I SET updated_at = atualizado_em WHERE updated_at IS NULL', target_table);
    ELSE
        -- Ensure 'atualizado_em' exists as a fallback to avoid trigger errors
        EXECUTE format('ALTER TABLE public.%I ADD COLUMN atualizado_em TIMESTAMPTZ DEFAULT now()', target_table);
    END IF;
END;
$$;


ALTER FUNCTION "public"."standardize_table_timestamps"("target_table" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_produtos_updated_at_column"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_produtos_updated_at_column"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_updated_at_column"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_updated_at_column"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "storage"."can_insert_object"("bucketid" "text", "name" "text", "owner" "uuid", "metadata" "jsonb") RETURNS "void"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
  INSERT INTO "storage"."objects" ("bucket_id", "name", "owner", "metadata") VALUES (bucketid, name, owner, metadata);
  -- hack to rollback the successful insert
  RAISE sqlstate 'PT200' using
  message = 'ROLLBACK',
  detail = 'rollback successful insert';
END
$$;


ALTER FUNCTION "storage"."can_insert_object"("bucketid" "text", "name" "text", "owner" "uuid", "metadata" "jsonb") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."delete_leaf_prefixes"("bucket_ids" "text"[], "names" "text"[]) RETURNS "void"
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
DECLARE
    v_rows_deleted integer;
BEGIN
    LOOP
        WITH candidates AS (
            SELECT DISTINCT
                t.bucket_id,
                unnest(storage.get_prefixes(t.name)) AS name
            FROM unnest(bucket_ids, names) AS t(bucket_id, name)
        ),
        uniq AS (
             SELECT
                 bucket_id,
                 name,
                 storage.get_level(name) AS level
             FROM candidates
             WHERE name <> ''
             GROUP BY bucket_id, name
        ),
        leaf AS (
             SELECT
                 p.bucket_id,
                 p.name,
                 p.level
             FROM storage.prefixes AS p
                  JOIN uniq AS u
                       ON u.bucket_id = p.bucket_id
                           AND u.name = p.name
                           AND u.level = p.level
             WHERE NOT EXISTS (
                 SELECT 1
                 FROM storage.objects AS o
                 WHERE o.bucket_id = p.bucket_id
                   AND o.level = p.level + 1
                   AND o.name COLLATE "C" LIKE p.name || '/%'
             )
             AND NOT EXISTS (
                 SELECT 1
                 FROM storage.prefixes AS c
                 WHERE c.bucket_id = p.bucket_id
                   AND c.level = p.level + 1
                   AND c.name COLLATE "C" LIKE p.name || '/%'
             )
        )
        DELETE
        FROM storage.prefixes AS p
            USING leaf AS l
        WHERE p.bucket_id = l.bucket_id
          AND p.name = l.name
          AND p.level = l.level;

        GET DIAGNOSTICS v_rows_deleted = ROW_COUNT;
        EXIT WHEN v_rows_deleted = 0;
    END LOOP;
END;
$$;


ALTER FUNCTION "storage"."delete_leaf_prefixes"("bucket_ids" "text"[], "names" "text"[]) OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."enforce_bucket_name_length"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
begin
    if length(new.name) > 100 then
        raise exception 'bucket name "%" is too long (% characters). Max is 100.', new.name, length(new.name);
    end if;
    return new;
end;
$$;


ALTER FUNCTION "storage"."enforce_bucket_name_length"() OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."extension"("name" "text") RETURNS "text"
    LANGUAGE "plpgsql" IMMUTABLE
    AS $$
DECLARE
    _parts text[];
    _filename text;
BEGIN
    SELECT string_to_array(name, '/') INTO _parts;
    SELECT _parts[array_length(_parts,1)] INTO _filename;
    RETURN reverse(split_part(reverse(_filename), '.', 1));
END
$$;


ALTER FUNCTION "storage"."extension"("name" "text") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."filename"("name" "text") RETURNS "text"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
_parts text[];
BEGIN
	select string_to_array(name, '/') into _parts;
	return _parts[array_length(_parts,1)];
END
$$;


ALTER FUNCTION "storage"."filename"("name" "text") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."foldername"("name" "text") RETURNS "text"[]
    LANGUAGE "plpgsql" IMMUTABLE
    AS $$
DECLARE
    _parts text[];
BEGIN
    -- Split on "/" to get path segments
    SELECT string_to_array(name, '/') INTO _parts;
    -- Return everything except the last segment
    RETURN _parts[1 : array_length(_parts,1) - 1];
END
$$;


ALTER FUNCTION "storage"."foldername"("name" "text") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."get_common_prefix"("p_key" "text", "p_prefix" "text", "p_delimiter" "text") RETURNS "text"
    LANGUAGE "sql" IMMUTABLE
    AS $$
SELECT CASE
    WHEN position(p_delimiter IN substring(p_key FROM length(p_prefix) + 1)) > 0
    THEN left(p_key, length(p_prefix) + position(p_delimiter IN substring(p_key FROM length(p_prefix) + 1)))
    ELSE NULL
END;
$$;


ALTER FUNCTION "storage"."get_common_prefix"("p_key" "text", "p_prefix" "text", "p_delimiter" "text") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."get_level"("name" "text") RETURNS integer
    LANGUAGE "sql" IMMUTABLE STRICT
    AS $$
SELECT array_length(string_to_array("name", '/'), 1);
$$;


ALTER FUNCTION "storage"."get_level"("name" "text") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."get_prefix"("name" "text") RETURNS "text"
    LANGUAGE "sql" IMMUTABLE STRICT
    AS $_$
SELECT
    CASE WHEN strpos("name", '/') > 0 THEN
             regexp_replace("name", '[\/]{1}[^\/]+\/?$', '')
         ELSE
             ''
        END;
$_$;


ALTER FUNCTION "storage"."get_prefix"("name" "text") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."get_prefixes"("name" "text") RETURNS "text"[]
    LANGUAGE "plpgsql" IMMUTABLE STRICT
    AS $$
DECLARE
    parts text[];
    prefixes text[];
    prefix text;
BEGIN
    -- Split the name into parts by '/'
    parts := string_to_array("name", '/');
    prefixes := '{}';

    -- Construct the prefixes, stopping one level below the last part
    FOR i IN 1..array_length(parts, 1) - 1 LOOP
            prefix := array_to_string(parts[1:i], '/');
            prefixes := array_append(prefixes, prefix);
    END LOOP;

    RETURN prefixes;
END;
$$;


ALTER FUNCTION "storage"."get_prefixes"("name" "text") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."get_size_by_bucket"() RETURNS TABLE("size" bigint, "bucket_id" "text")
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    return query
        select sum((metadata->>'size')::bigint) as size, obj.bucket_id
        from "storage".objects as obj
        group by obj.bucket_id;
END
$$;


ALTER FUNCTION "storage"."get_size_by_bucket"() OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."list_multipart_uploads_with_delimiter"("bucket_id" "text", "prefix_param" "text", "delimiter_param" "text", "max_keys" integer DEFAULT 100, "next_key_token" "text" DEFAULT ''::"text", "next_upload_token" "text" DEFAULT ''::"text") RETURNS TABLE("key" "text", "id" "text", "created_at" timestamp with time zone)
    LANGUAGE "plpgsql"
    AS $_$
BEGIN
    RETURN QUERY EXECUTE
        'SELECT DISTINCT ON(key COLLATE "C") * from (
            SELECT
                CASE
                    WHEN position($2 IN substring(key from length($1) + 1)) > 0 THEN
                        substring(key from 1 for length($1) + position($2 IN substring(key from length($1) + 1)))
                    ELSE
                        key
                END AS key, id, created_at
            FROM
                storage.s3_multipart_uploads
            WHERE
                bucket_id = $5 AND
                key ILIKE $1 || ''%'' AND
                CASE
                    WHEN $4 != '''' AND $6 = '''' THEN
                        CASE
                            WHEN position($2 IN substring(key from length($1) + 1)) > 0 THEN
                                substring(key from 1 for length($1) + position($2 IN substring(key from length($1) + 1))) COLLATE "C" > $4
                            ELSE
                                key COLLATE "C" > $4
                            END
                    ELSE
                        true
                END AND
                CASE
                    WHEN $6 != '''' THEN
                        id COLLATE "C" > $6
                    ELSE
                        true
                    END
            ORDER BY
                key COLLATE "C" ASC, created_at ASC) as e order by key COLLATE "C" LIMIT $3'
        USING prefix_param, delimiter_param, max_keys, next_key_token, bucket_id, next_upload_token;
END;
$_$;


ALTER FUNCTION "storage"."list_multipart_uploads_with_delimiter"("bucket_id" "text", "prefix_param" "text", "delimiter_param" "text", "max_keys" integer, "next_key_token" "text", "next_upload_token" "text") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."list_objects_with_delimiter"("_bucket_id" "text", "prefix_param" "text", "delimiter_param" "text", "max_keys" integer DEFAULT 100, "start_after" "text" DEFAULT ''::"text", "next_token" "text" DEFAULT ''::"text", "sort_order" "text" DEFAULT 'asc'::"text") RETURNS TABLE("name" "text", "id" "uuid", "metadata" "jsonb", "updated_at" timestamp with time zone, "created_at" timestamp with time zone, "last_accessed_at" timestamp with time zone)
    LANGUAGE "plpgsql" STABLE
    AS $_$
DECLARE
    v_peek_name TEXT;
    v_current RECORD;
    v_common_prefix TEXT;

    -- Configuration
    v_is_asc BOOLEAN;
    v_prefix TEXT;
    v_start TEXT;
    v_upper_bound TEXT;
    v_file_batch_size INT;

    -- Seek state
    v_next_seek TEXT;
    v_count INT := 0;

    -- Dynamic SQL for batch query only
    v_batch_query TEXT;

BEGIN
    -- ========================================================================
    -- INITIALIZATION
    -- ========================================================================
    v_is_asc := lower(coalesce(sort_order, 'asc')) = 'asc';
    v_prefix := coalesce(prefix_param, '');
    v_start := CASE WHEN coalesce(next_token, '') <> '' THEN next_token ELSE coalesce(start_after, '') END;
    v_file_batch_size := LEAST(GREATEST(max_keys * 2, 100), 1000);

    -- Calculate upper bound for prefix filtering (bytewise, using COLLATE "C")
    IF v_prefix = '' THEN
        v_upper_bound := NULL;
    ELSIF right(v_prefix, 1) = delimiter_param THEN
        v_upper_bound := left(v_prefix, -1) || chr(ascii(delimiter_param) + 1);
    ELSE
        v_upper_bound := left(v_prefix, -1) || chr(ascii(right(v_prefix, 1)) + 1);
    END IF;

    -- Build batch query (dynamic SQL - called infrequently, amortized over many rows)
    IF v_is_asc THEN
        IF v_upper_bound IS NOT NULL THEN
            v_batch_query := 'SELECT o.name, o.id, o.updated_at, o.created_at, o.last_accessed_at, o.metadata ' ||
                'FROM storage.objects o WHERE o.bucket_id = $1 AND o.name COLLATE "C" >= $2 ' ||
                'AND o.name COLLATE "C" < $3 ORDER BY o.name COLLATE "C" ASC LIMIT $4';
        ELSE
            v_batch_query := 'SELECT o.name, o.id, o.updated_at, o.created_at, o.last_accessed_at, o.metadata ' ||
                'FROM storage.objects o WHERE o.bucket_id = $1 AND o.name COLLATE "C" >= $2 ' ||
                'ORDER BY o.name COLLATE "C" ASC LIMIT $4';
        END IF;
    ELSE
        IF v_upper_bound IS NOT NULL THEN
            v_batch_query := 'SELECT o.name, o.id, o.updated_at, o.created_at, o.last_accessed_at, o.metadata ' ||
                'FROM storage.objects o WHERE o.bucket_id = $1 AND o.name COLLATE "C" < $2 ' ||
                'AND o.name COLLATE "C" >= $3 ORDER BY o.name COLLATE "C" DESC LIMIT $4';
        ELSE
            v_batch_query := 'SELECT o.name, o.id, o.updated_at, o.created_at, o.last_accessed_at, o.metadata ' ||
                'FROM storage.objects o WHERE o.bucket_id = $1 AND o.name COLLATE "C" < $2 ' ||
                'ORDER BY o.name COLLATE "C" DESC LIMIT $4';
        END IF;
    END IF;

    -- ========================================================================
    -- SEEK INITIALIZATION: Determine starting position
    -- ========================================================================
    IF v_start = '' THEN
        IF v_is_asc THEN
            v_next_seek := v_prefix;
        ELSE
            -- DESC without cursor: find the last item in range
            IF v_upper_bound IS NOT NULL THEN
                SELECT o.name INTO v_next_seek FROM storage.objects o
                WHERE o.bucket_id = _bucket_id AND o.name COLLATE "C" >= v_prefix AND o.name COLLATE "C" < v_upper_bound
                ORDER BY o.name COLLATE "C" DESC LIMIT 1;
            ELSIF v_prefix <> '' THEN
                SELECT o.name INTO v_next_seek FROM storage.objects o
                WHERE o.bucket_id = _bucket_id AND o.name COLLATE "C" >= v_prefix
                ORDER BY o.name COLLATE "C" DESC LIMIT 1;
            ELSE
                SELECT o.name INTO v_next_seek FROM storage.objects o
                WHERE o.bucket_id = _bucket_id
                ORDER BY o.name COLLATE "C" DESC LIMIT 1;
            END IF;

            IF v_next_seek IS NOT NULL THEN
                v_next_seek := v_next_seek || delimiter_param;
            ELSE
                RETURN;
            END IF;
        END IF;
    ELSE
        -- Cursor provided: determine if it refers to a folder or leaf
        IF EXISTS (
            SELECT 1 FROM storage.objects o
            WHERE o.bucket_id = _bucket_id
              AND o.name COLLATE "C" LIKE v_start || delimiter_param || '%'
            LIMIT 1
        ) THEN
            -- Cursor refers to a folder
            IF v_is_asc THEN
                v_next_seek := v_start || chr(ascii(delimiter_param) + 1);
            ELSE
                v_next_seek := v_start || delimiter_param;
            END IF;
        ELSE
            -- Cursor refers to a leaf object
            IF v_is_asc THEN
                v_next_seek := v_start || delimiter_param;
            ELSE
                v_next_seek := v_start;
            END IF;
        END IF;
    END IF;

    -- ========================================================================
    -- MAIN LOOP: Hybrid peek-then-batch algorithm
    -- Uses STATIC SQL for peek (hot path) and DYNAMIC SQL for batch
    -- ========================================================================
    LOOP
        EXIT WHEN v_count >= max_keys;

        -- STEP 1: PEEK using STATIC SQL (plan cached, very fast)
        IF v_is_asc THEN
            IF v_upper_bound IS NOT NULL THEN
                SELECT o.name INTO v_peek_name FROM storage.objects o
                WHERE o.bucket_id = _bucket_id AND o.name COLLATE "C" >= v_next_seek AND o.name COLLATE "C" < v_upper_bound
                ORDER BY o.name COLLATE "C" ASC LIMIT 1;
            ELSE
                SELECT o.name INTO v_peek_name FROM storage.objects o
                WHERE o.bucket_id = _bucket_id AND o.name COLLATE "C" >= v_next_seek
                ORDER BY o.name COLLATE "C" ASC LIMIT 1;
            END IF;
        ELSE
            IF v_upper_bound IS NOT NULL THEN
                SELECT o.name INTO v_peek_name FROM storage.objects o
                WHERE o.bucket_id = _bucket_id AND o.name COLLATE "C" < v_next_seek AND o.name COLLATE "C" >= v_prefix
                ORDER BY o.name COLLATE "C" DESC LIMIT 1;
            ELSIF v_prefix <> '' THEN
                SELECT o.name INTO v_peek_name FROM storage.objects o
                WHERE o.bucket_id = _bucket_id AND o.name COLLATE "C" < v_next_seek AND o.name COLLATE "C" >= v_prefix
                ORDER BY o.name COLLATE "C" DESC LIMIT 1;
            ELSE
                SELECT o.name INTO v_peek_name FROM storage.objects o
                WHERE o.bucket_id = _bucket_id AND o.name COLLATE "C" < v_next_seek
                ORDER BY o.name COLLATE "C" DESC LIMIT 1;
            END IF;
        END IF;

        EXIT WHEN v_peek_name IS NULL;

        -- STEP 2: Check if this is a FOLDER or FILE
        v_common_prefix := storage.get_common_prefix(v_peek_name, v_prefix, delimiter_param);

        IF v_common_prefix IS NOT NULL THEN
            -- FOLDER: Emit and skip to next folder (no heap access needed)
            name := rtrim(v_common_prefix, delimiter_param);
            id := NULL;
            updated_at := NULL;
            created_at := NULL;
            last_accessed_at := NULL;
            metadata := NULL;
            RETURN NEXT;
            v_count := v_count + 1;

            -- Advance seek past the folder range
            IF v_is_asc THEN
                v_next_seek := left(v_common_prefix, -1) || chr(ascii(delimiter_param) + 1);
            ELSE
                v_next_seek := v_common_prefix;
            END IF;
        ELSE
            -- FILE: Batch fetch using DYNAMIC SQL (overhead amortized over many rows)
            -- For ASC: upper_bound is the exclusive upper limit (< condition)
            -- For DESC: prefix is the inclusive lower limit (>= condition)
            FOR v_current IN EXECUTE v_batch_query USING _bucket_id, v_next_seek,
                CASE WHEN v_is_asc THEN COALESCE(v_upper_bound, v_prefix) ELSE v_prefix END, v_file_batch_size
            LOOP
                v_common_prefix := storage.get_common_prefix(v_current.name, v_prefix, delimiter_param);

                IF v_common_prefix IS NOT NULL THEN
                    -- Hit a folder: exit batch, let peek handle it
                    v_next_seek := v_current.name;
                    EXIT;
                END IF;

                -- Emit file
                name := v_current.name;
                id := v_current.id;
                updated_at := v_current.updated_at;
                created_at := v_current.created_at;
                last_accessed_at := v_current.last_accessed_at;
                metadata := v_current.metadata;
                RETURN NEXT;
                v_count := v_count + 1;

                -- Advance seek past this file
                IF v_is_asc THEN
                    v_next_seek := v_current.name || delimiter_param;
                ELSE
                    v_next_seek := v_current.name;
                END IF;

                EXIT WHEN v_count >= max_keys;
            END LOOP;
        END IF;
    END LOOP;
END;
$_$;


ALTER FUNCTION "storage"."list_objects_with_delimiter"("_bucket_id" "text", "prefix_param" "text", "delimiter_param" "text", "max_keys" integer, "start_after" "text", "next_token" "text", "sort_order" "text") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."operation"() RETURNS "text"
    LANGUAGE "plpgsql" STABLE
    AS $$
BEGIN
    RETURN current_setting('storage.operation', true);
END;
$$;


ALTER FUNCTION "storage"."operation"() OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."protect_delete"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    -- Check if storage.allow_delete_query is set to 'true'
    IF COALESCE(current_setting('storage.allow_delete_query', true), 'false') != 'true' THEN
        RAISE EXCEPTION 'Direct deletion from storage tables is not allowed. Use the Storage API instead.'
            USING HINT = 'This prevents accidental data loss from orphaned objects.',
                  ERRCODE = '42501';
    END IF;
    RETURN NULL;
END;
$$;


ALTER FUNCTION "storage"."protect_delete"() OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."search"("prefix" "text", "bucketname" "text", "limits" integer DEFAULT 100, "levels" integer DEFAULT 1, "offsets" integer DEFAULT 0, "search" "text" DEFAULT ''::"text", "sortcolumn" "text" DEFAULT 'name'::"text", "sortorder" "text" DEFAULT 'asc'::"text") RETURNS TABLE("name" "text", "id" "uuid", "updated_at" timestamp with time zone, "created_at" timestamp with time zone, "last_accessed_at" timestamp with time zone, "metadata" "jsonb")
    LANGUAGE "plpgsql" STABLE
    AS $_$
DECLARE
    v_peek_name TEXT;
    v_current RECORD;
    v_common_prefix TEXT;
    v_delimiter CONSTANT TEXT := '/';

    -- Configuration
    v_limit INT;
    v_prefix TEXT;
    v_prefix_lower TEXT;
    v_is_asc BOOLEAN;
    v_order_by TEXT;
    v_sort_order TEXT;
    v_upper_bound TEXT;
    v_file_batch_size INT;

    -- Dynamic SQL for batch query only
    v_batch_query TEXT;

    -- Seek state
    v_next_seek TEXT;
    v_count INT := 0;
    v_skipped INT := 0;
BEGIN
    -- ========================================================================
    -- INITIALIZATION
    -- ========================================================================
    v_limit := LEAST(coalesce(limits, 100), 1500);
    v_prefix := coalesce(prefix, '') || coalesce(search, '');
    v_prefix_lower := lower(v_prefix);
    v_is_asc := lower(coalesce(sortorder, 'asc')) = 'asc';
    v_file_batch_size := LEAST(GREATEST(v_limit * 2, 100), 1000);

    -- Validate sort column
    CASE lower(coalesce(sortcolumn, 'name'))
        WHEN 'name' THEN v_order_by := 'name';
        WHEN 'updated_at' THEN v_order_by := 'updated_at';
        WHEN 'created_at' THEN v_order_by := 'created_at';
        WHEN 'last_accessed_at' THEN v_order_by := 'last_accessed_at';
        ELSE v_order_by := 'name';
    END CASE;

    v_sort_order := CASE WHEN v_is_asc THEN 'asc' ELSE 'desc' END;

    -- ========================================================================
    -- NON-NAME SORTING: Use path_tokens approach (unchanged)
    -- ========================================================================
    IF v_order_by != 'name' THEN
        RETURN QUERY EXECUTE format(
            $sql$
            WITH folders AS (
                SELECT path_tokens[$1] AS folder
                FROM storage.objects
                WHERE objects.name ILIKE $2 || '%%'
                  AND bucket_id = $3
                  AND array_length(objects.path_tokens, 1) <> $1
                GROUP BY folder
                ORDER BY folder %s
            )
            (SELECT folder AS "name",
                   NULL::uuid AS id,
                   NULL::timestamptz AS updated_at,
                   NULL::timestamptz AS created_at,
                   NULL::timestamptz AS last_accessed_at,
                   NULL::jsonb AS metadata FROM folders)
            UNION ALL
            (SELECT path_tokens[$1] AS "name",
                   id, updated_at, created_at, last_accessed_at, metadata
             FROM storage.objects
             WHERE objects.name ILIKE $2 || '%%'
               AND bucket_id = $3
               AND array_length(objects.path_tokens, 1) = $1
             ORDER BY %I %s)
            LIMIT $4 OFFSET $5
            $sql$, v_sort_order, v_order_by, v_sort_order
        ) USING levels, v_prefix, bucketname, v_limit, offsets;
        RETURN;
    END IF;

    -- ========================================================================
    -- NAME SORTING: Hybrid skip-scan with batch optimization
    -- ========================================================================

    -- Calculate upper bound for prefix filtering
    IF v_prefix_lower = '' THEN
        v_upper_bound := NULL;
    ELSIF right(v_prefix_lower, 1) = v_delimiter THEN
        v_upper_bound := left(v_prefix_lower, -1) || chr(ascii(v_delimiter) + 1);
    ELSE
        v_upper_bound := left(v_prefix_lower, -1) || chr(ascii(right(v_prefix_lower, 1)) + 1);
    END IF;

    -- Build batch query (dynamic SQL - called infrequently, amortized over many rows)
    IF v_is_asc THEN
        IF v_upper_bound IS NOT NULL THEN
            v_batch_query := 'SELECT o.name, o.id, o.updated_at, o.created_at, o.last_accessed_at, o.metadata ' ||
                'FROM storage.objects o WHERE o.bucket_id = $1 AND lower(o.name) COLLATE "C" >= $2 ' ||
                'AND lower(o.name) COLLATE "C" < $3 ORDER BY lower(o.name) COLLATE "C" ASC LIMIT $4';
        ELSE
            v_batch_query := 'SELECT o.name, o.id, o.updated_at, o.created_at, o.last_accessed_at, o.metadata ' ||
                'FROM storage.objects o WHERE o.bucket_id = $1 AND lower(o.name) COLLATE "C" >= $2 ' ||
                'ORDER BY lower(o.name) COLLATE "C" ASC LIMIT $4';
        END IF;
    ELSE
        IF v_upper_bound IS NOT NULL THEN
            v_batch_query := 'SELECT o.name, o.id, o.updated_at, o.created_at, o.last_accessed_at, o.metadata ' ||
                'FROM storage.objects o WHERE o.bucket_id = $1 AND lower(o.name) COLLATE "C" < $2 ' ||
                'AND lower(o.name) COLLATE "C" >= $3 ORDER BY lower(o.name) COLLATE "C" DESC LIMIT $4';
        ELSE
            v_batch_query := 'SELECT o.name, o.id, o.updated_at, o.created_at, o.last_accessed_at, o.metadata ' ||
                'FROM storage.objects o WHERE o.bucket_id = $1 AND lower(o.name) COLLATE "C" < $2 ' ||
                'ORDER BY lower(o.name) COLLATE "C" DESC LIMIT $4';
        END IF;
    END IF;

    -- Initialize seek position
    IF v_is_asc THEN
        v_next_seek := v_prefix_lower;
    ELSE
        -- DESC: find the last item in range first (static SQL)
        IF v_upper_bound IS NOT NULL THEN
            SELECT o.name INTO v_peek_name FROM storage.objects o
            WHERE o.bucket_id = bucketname AND lower(o.name) COLLATE "C" >= v_prefix_lower AND lower(o.name) COLLATE "C" < v_upper_bound
            ORDER BY lower(o.name) COLLATE "C" DESC LIMIT 1;
        ELSIF v_prefix_lower <> '' THEN
            SELECT o.name INTO v_peek_name FROM storage.objects o
            WHERE o.bucket_id = bucketname AND lower(o.name) COLLATE "C" >= v_prefix_lower
            ORDER BY lower(o.name) COLLATE "C" DESC LIMIT 1;
        ELSE
            SELECT o.name INTO v_peek_name FROM storage.objects o
            WHERE o.bucket_id = bucketname
            ORDER BY lower(o.name) COLLATE "C" DESC LIMIT 1;
        END IF;

        IF v_peek_name IS NOT NULL THEN
            v_next_seek := lower(v_peek_name) || v_delimiter;
        ELSE
            RETURN;
        END IF;
    END IF;

    -- ========================================================================
    -- MAIN LOOP: Hybrid peek-then-batch algorithm
    -- Uses STATIC SQL for peek (hot path) and DYNAMIC SQL for batch
    -- ========================================================================
    LOOP
        EXIT WHEN v_count >= v_limit;

        -- STEP 1: PEEK using STATIC SQL (plan cached, very fast)
        IF v_is_asc THEN
            IF v_upper_bound IS NOT NULL THEN
                SELECT o.name INTO v_peek_name FROM storage.objects o
                WHERE o.bucket_id = bucketname AND lower(o.name) COLLATE "C" >= v_next_seek AND lower(o.name) COLLATE "C" < v_upper_bound
                ORDER BY lower(o.name) COLLATE "C" ASC LIMIT 1;
            ELSE
                SELECT o.name INTO v_peek_name FROM storage.objects o
                WHERE o.bucket_id = bucketname AND lower(o.name) COLLATE "C" >= v_next_seek
                ORDER BY lower(o.name) COLLATE "C" ASC LIMIT 1;
            END IF;
        ELSE
            IF v_upper_bound IS NOT NULL THEN
                SELECT o.name INTO v_peek_name FROM storage.objects o
                WHERE o.bucket_id = bucketname AND lower(o.name) COLLATE "C" < v_next_seek AND lower(o.name) COLLATE "C" >= v_prefix_lower
                ORDER BY lower(o.name) COLLATE "C" DESC LIMIT 1;
            ELSIF v_prefix_lower <> '' THEN
                SELECT o.name INTO v_peek_name FROM storage.objects o
                WHERE o.bucket_id = bucketname AND lower(o.name) COLLATE "C" < v_next_seek AND lower(o.name) COLLATE "C" >= v_prefix_lower
                ORDER BY lower(o.name) COLLATE "C" DESC LIMIT 1;
            ELSE
                SELECT o.name INTO v_peek_name FROM storage.objects o
                WHERE o.bucket_id = bucketname AND lower(o.name) COLLATE "C" < v_next_seek
                ORDER BY lower(o.name) COLLATE "C" DESC LIMIT 1;
            END IF;
        END IF;

        EXIT WHEN v_peek_name IS NULL;

        -- STEP 2: Check if this is a FOLDER or FILE
        v_common_prefix := storage.get_common_prefix(lower(v_peek_name), v_prefix_lower, v_delimiter);

        IF v_common_prefix IS NOT NULL THEN
            -- FOLDER: Handle offset, emit if needed, skip to next folder
            IF v_skipped < offsets THEN
                v_skipped := v_skipped + 1;
            ELSE
                name := split_part(rtrim(storage.get_common_prefix(v_peek_name, v_prefix, v_delimiter), v_delimiter), v_delimiter, levels);
                id := NULL;
                updated_at := NULL;
                created_at := NULL;
                last_accessed_at := NULL;
                metadata := NULL;
                RETURN NEXT;
                v_count := v_count + 1;
            END IF;

            -- Advance seek past the folder range
            IF v_is_asc THEN
                v_next_seek := lower(left(v_common_prefix, -1)) || chr(ascii(v_delimiter) + 1);
            ELSE
                v_next_seek := lower(v_common_prefix);
            END IF;
        ELSE
            -- FILE: Batch fetch using DYNAMIC SQL (overhead amortized over many rows)
            -- For ASC: upper_bound is the exclusive upper limit (< condition)
            -- For DESC: prefix_lower is the inclusive lower limit (>= condition)
            FOR v_current IN EXECUTE v_batch_query
                USING bucketname, v_next_seek,
                    CASE WHEN v_is_asc THEN COALESCE(v_upper_bound, v_prefix_lower) ELSE v_prefix_lower END, v_file_batch_size
            LOOP
                v_common_prefix := storage.get_common_prefix(lower(v_current.name), v_prefix_lower, v_delimiter);

                IF v_common_prefix IS NOT NULL THEN
                    -- Hit a folder: exit batch, let peek handle it
                    v_next_seek := lower(v_current.name);
                    EXIT;
                END IF;

                -- Handle offset skipping
                IF v_skipped < offsets THEN
                    v_skipped := v_skipped + 1;
                ELSE
                    -- Emit file
                    name := split_part(v_current.name, v_delimiter, levels);
                    id := v_current.id;
                    updated_at := v_current.updated_at;
                    created_at := v_current.created_at;
                    last_accessed_at := v_current.last_accessed_at;
                    metadata := v_current.metadata;
                    RETURN NEXT;
                    v_count := v_count + 1;
                END IF;

                -- Advance seek past this file
                IF v_is_asc THEN
                    v_next_seek := lower(v_current.name) || v_delimiter;
                ELSE
                    v_next_seek := lower(v_current.name);
                END IF;

                EXIT WHEN v_count >= v_limit;
            END LOOP;
        END IF;
    END LOOP;
END;
$_$;


ALTER FUNCTION "storage"."search"("prefix" "text", "bucketname" "text", "limits" integer, "levels" integer, "offsets" integer, "search" "text", "sortcolumn" "text", "sortorder" "text") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."search_by_timestamp"("p_prefix" "text", "p_bucket_id" "text", "p_limit" integer, "p_level" integer, "p_start_after" "text", "p_sort_order" "text", "p_sort_column" "text", "p_sort_column_after" "text") RETURNS TABLE("key" "text", "name" "text", "id" "uuid", "updated_at" timestamp with time zone, "created_at" timestamp with time zone, "last_accessed_at" timestamp with time zone, "metadata" "jsonb")
    LANGUAGE "plpgsql" STABLE
    AS $_$
DECLARE
    v_cursor_op text;
    v_query text;
    v_prefix text;
BEGIN
    v_prefix := coalesce(p_prefix, '');

    IF p_sort_order = 'asc' THEN
        v_cursor_op := '>';
    ELSE
        v_cursor_op := '<';
    END IF;

    v_query := format($sql$
        WITH raw_objects AS (
            SELECT
                o.name AS obj_name,
                o.id AS obj_id,
                o.updated_at AS obj_updated_at,
                o.created_at AS obj_created_at,
                o.last_accessed_at AS obj_last_accessed_at,
                o.metadata AS obj_metadata,
                storage.get_common_prefix(o.name, $1, '/') AS common_prefix
            FROM storage.objects o
            WHERE o.bucket_id = $2
              AND o.name COLLATE "C" LIKE $1 || '%%'
        ),
        -- Aggregate common prefixes (folders)
        -- Both created_at and updated_at use MIN(obj_created_at) to match the old prefixes table behavior
        aggregated_prefixes AS (
            SELECT
                rtrim(common_prefix, '/') AS name,
                NULL::uuid AS id,
                MIN(obj_created_at) AS updated_at,
                MIN(obj_created_at) AS created_at,
                NULL::timestamptz AS last_accessed_at,
                NULL::jsonb AS metadata,
                TRUE AS is_prefix
            FROM raw_objects
            WHERE common_prefix IS NOT NULL
            GROUP BY common_prefix
        ),
        leaf_objects AS (
            SELECT
                obj_name AS name,
                obj_id AS id,
                obj_updated_at AS updated_at,
                obj_created_at AS created_at,
                obj_last_accessed_at AS last_accessed_at,
                obj_metadata AS metadata,
                FALSE AS is_prefix
            FROM raw_objects
            WHERE common_prefix IS NULL
        ),
        combined AS (
            SELECT * FROM aggregated_prefixes
            UNION ALL
            SELECT * FROM leaf_objects
        ),
        filtered AS (
            SELECT *
            FROM combined
            WHERE (
                $5 = ''
                OR ROW(
                    date_trunc('milliseconds', %I),
                    name COLLATE "C"
                ) %s ROW(
                    COALESCE(NULLIF($6, '')::timestamptz, 'epoch'::timestamptz),
                    $5
                )
            )
        )
        SELECT
            split_part(name, '/', $3) AS key,
            name,
            id,
            updated_at,
            created_at,
            last_accessed_at,
            metadata
        FROM filtered
        ORDER BY
            COALESCE(date_trunc('milliseconds', %I), 'epoch'::timestamptz) %s,
            name COLLATE "C" %s
        LIMIT $4
    $sql$,
        p_sort_column,
        v_cursor_op,
        p_sort_column,
        p_sort_order,
        p_sort_order
    );

    RETURN QUERY EXECUTE v_query
    USING v_prefix, p_bucket_id, p_level, p_limit, p_start_after, p_sort_column_after;
END;
$_$;


ALTER FUNCTION "storage"."search_by_timestamp"("p_prefix" "text", "p_bucket_id" "text", "p_limit" integer, "p_level" integer, "p_start_after" "text", "p_sort_order" "text", "p_sort_column" "text", "p_sort_column_after" "text") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."search_legacy_v1"("prefix" "text", "bucketname" "text", "limits" integer DEFAULT 100, "levels" integer DEFAULT 1, "offsets" integer DEFAULT 0, "search" "text" DEFAULT ''::"text", "sortcolumn" "text" DEFAULT 'name'::"text", "sortorder" "text" DEFAULT 'asc'::"text") RETURNS TABLE("name" "text", "id" "uuid", "updated_at" timestamp with time zone, "created_at" timestamp with time zone, "last_accessed_at" timestamp with time zone, "metadata" "jsonb")
    LANGUAGE "plpgsql" STABLE
    AS $_$
declare
    v_order_by text;
    v_sort_order text;
begin
    case
        when sortcolumn = 'name' then
            v_order_by = 'name';
        when sortcolumn = 'updated_at' then
            v_order_by = 'updated_at';
        when sortcolumn = 'created_at' then
            v_order_by = 'created_at';
        when sortcolumn = 'last_accessed_at' then
            v_order_by = 'last_accessed_at';
        else
            v_order_by = 'name';
        end case;

    case
        when sortorder = 'asc' then
            v_sort_order = 'asc';
        when sortorder = 'desc' then
            v_sort_order = 'desc';
        else
            v_sort_order = 'asc';
        end case;

    v_order_by = v_order_by || ' ' || v_sort_order;

    return query execute
        'with folders as (
           select path_tokens[$1] as folder
           from storage.objects
             where objects.name ilike $2 || $3 || ''%''
               and bucket_id = $4
               and array_length(objects.path_tokens, 1) <> $1
           group by folder
           order by folder ' || v_sort_order || '
     )
     (select folder as "name",
            null as id,
            null as updated_at,
            null as created_at,
            null as last_accessed_at,
            null as metadata from folders)
     union all
     (select path_tokens[$1] as "name",
            id,
            updated_at,
            created_at,
            last_accessed_at,
            metadata
     from storage.objects
     where objects.name ilike $2 || $3 || ''%''
       and bucket_id = $4
       and array_length(objects.path_tokens, 1) = $1
     order by ' || v_order_by || ')
     limit $5
     offset $6' using levels, prefix, search, bucketname, limits, offsets;
end;
$_$;


ALTER FUNCTION "storage"."search_legacy_v1"("prefix" "text", "bucketname" "text", "limits" integer, "levels" integer, "offsets" integer, "search" "text", "sortcolumn" "text", "sortorder" "text") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."search_v2"("prefix" "text", "bucket_name" "text", "limits" integer DEFAULT 100, "levels" integer DEFAULT 1, "start_after" "text" DEFAULT ''::"text", "sort_order" "text" DEFAULT 'asc'::"text", "sort_column" "text" DEFAULT 'name'::"text", "sort_column_after" "text" DEFAULT ''::"text") RETURNS TABLE("key" "text", "name" "text", "id" "uuid", "updated_at" timestamp with time zone, "created_at" timestamp with time zone, "last_accessed_at" timestamp with time zone, "metadata" "jsonb")
    LANGUAGE "plpgsql" STABLE
    AS $$
DECLARE
    v_sort_col text;
    v_sort_ord text;
    v_limit int;
BEGIN
    -- Cap limit to maximum of 1500 records
    v_limit := LEAST(coalesce(limits, 100), 1500);

    -- Validate and normalize sort_order
    v_sort_ord := lower(coalesce(sort_order, 'asc'));
    IF v_sort_ord NOT IN ('asc', 'desc') THEN
        v_sort_ord := 'asc';
    END IF;

    -- Validate and normalize sort_column
    v_sort_col := lower(coalesce(sort_column, 'name'));
    IF v_sort_col NOT IN ('name', 'updated_at', 'created_at') THEN
        v_sort_col := 'name';
    END IF;

    -- Route to appropriate implementation
    IF v_sort_col = 'name' THEN
        -- Use list_objects_with_delimiter for name sorting (most efficient: O(k * log n))
        RETURN QUERY
        SELECT
            split_part(l.name, '/', levels) AS key,
            l.name AS name,
            l.id,
            l.updated_at,
            l.created_at,
            l.last_accessed_at,
            l.metadata
        FROM storage.list_objects_with_delimiter(
            bucket_name,
            coalesce(prefix, ''),
            '/',
            v_limit,
            start_after,
            '',
            v_sort_ord
        ) l;
    ELSE
        -- Use aggregation approach for timestamp sorting
        -- Not efficient for large datasets but supports correct pagination
        RETURN QUERY SELECT * FROM storage.search_by_timestamp(
            prefix, bucket_name, v_limit, levels, start_after,
            v_sort_ord, v_sort_col, sort_column_after
        );
    END IF;
END;
$$;


ALTER FUNCTION "storage"."search_v2"("prefix" "text", "bucket_name" "text", "limits" integer, "levels" integer, "start_after" "text", "sort_order" "text", "sort_column" "text", "sort_column_after" "text") OWNER TO "supabase_storage_admin";


CREATE OR REPLACE FUNCTION "storage"."update_updated_at_column"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW; 
END;
$$;


ALTER FUNCTION "storage"."update_updated_at_column"() OWNER TO "supabase_storage_admin";

SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "auth"."audit_log_entries" (
    "instance_id" "uuid",
    "id" "uuid" NOT NULL,
    "payload" json,
    "created_at" timestamp with time zone,
    "ip_address" character varying(64) DEFAULT ''::character varying NOT NULL
);


ALTER TABLE "auth"."audit_log_entries" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."audit_log_entries" IS 'Auth: Audit trail for user actions.';



CREATE TABLE IF NOT EXISTS "auth"."custom_oauth_providers" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "provider_type" "text" NOT NULL,
    "identifier" "text" NOT NULL,
    "name" "text" NOT NULL,
    "client_id" "text" NOT NULL,
    "client_secret" "text" NOT NULL,
    "acceptable_client_ids" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "scopes" "text"[] DEFAULT '{}'::"text"[] NOT NULL,
    "pkce_enabled" boolean DEFAULT true NOT NULL,
    "attribute_mapping" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "authorization_params" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "enabled" boolean DEFAULT true NOT NULL,
    "email_optional" boolean DEFAULT false NOT NULL,
    "issuer" "text",
    "discovery_url" "text",
    "skip_nonce_check" boolean DEFAULT false NOT NULL,
    "cached_discovery" "jsonb",
    "discovery_cached_at" timestamp with time zone,
    "authorization_url" "text",
    "token_url" "text",
    "userinfo_url" "text",
    "jwks_uri" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "custom_oauth_providers_authorization_url_https" CHECK ((("authorization_url" IS NULL) OR ("authorization_url" ~~ 'https://%'::"text"))),
    CONSTRAINT "custom_oauth_providers_authorization_url_length" CHECK ((("authorization_url" IS NULL) OR ("char_length"("authorization_url") <= 2048))),
    CONSTRAINT "custom_oauth_providers_client_id_length" CHECK ((("char_length"("client_id") >= 1) AND ("char_length"("client_id") <= 512))),
    CONSTRAINT "custom_oauth_providers_discovery_url_length" CHECK ((("discovery_url" IS NULL) OR ("char_length"("discovery_url") <= 2048))),
    CONSTRAINT "custom_oauth_providers_identifier_format" CHECK (("identifier" ~ '^[a-z0-9][a-z0-9:-]{0,48}[a-z0-9]$'::"text")),
    CONSTRAINT "custom_oauth_providers_issuer_length" CHECK ((("issuer" IS NULL) OR (("char_length"("issuer") >= 1) AND ("char_length"("issuer") <= 2048)))),
    CONSTRAINT "custom_oauth_providers_jwks_uri_https" CHECK ((("jwks_uri" IS NULL) OR ("jwks_uri" ~~ 'https://%'::"text"))),
    CONSTRAINT "custom_oauth_providers_jwks_uri_length" CHECK ((("jwks_uri" IS NULL) OR ("char_length"("jwks_uri") <= 2048))),
    CONSTRAINT "custom_oauth_providers_name_length" CHECK ((("char_length"("name") >= 1) AND ("char_length"("name") <= 100))),
    CONSTRAINT "custom_oauth_providers_oauth2_requires_endpoints" CHECK ((("provider_type" <> 'oauth2'::"text") OR (("authorization_url" IS NOT NULL) AND ("token_url" IS NOT NULL) AND ("userinfo_url" IS NOT NULL)))),
    CONSTRAINT "custom_oauth_providers_oidc_discovery_url_https" CHECK ((("provider_type" <> 'oidc'::"text") OR ("discovery_url" IS NULL) OR ("discovery_url" ~~ 'https://%'::"text"))),
    CONSTRAINT "custom_oauth_providers_oidc_issuer_https" CHECK ((("provider_type" <> 'oidc'::"text") OR ("issuer" IS NULL) OR ("issuer" ~~ 'https://%'::"text"))),
    CONSTRAINT "custom_oauth_providers_oidc_requires_issuer" CHECK ((("provider_type" <> 'oidc'::"text") OR ("issuer" IS NOT NULL))),
    CONSTRAINT "custom_oauth_providers_provider_type_check" CHECK (("provider_type" = ANY (ARRAY['oauth2'::"text", 'oidc'::"text"]))),
    CONSTRAINT "custom_oauth_providers_token_url_https" CHECK ((("token_url" IS NULL) OR ("token_url" ~~ 'https://%'::"text"))),
    CONSTRAINT "custom_oauth_providers_token_url_length" CHECK ((("token_url" IS NULL) OR ("char_length"("token_url") <= 2048))),
    CONSTRAINT "custom_oauth_providers_userinfo_url_https" CHECK ((("userinfo_url" IS NULL) OR ("userinfo_url" ~~ 'https://%'::"text"))),
    CONSTRAINT "custom_oauth_providers_userinfo_url_length" CHECK ((("userinfo_url" IS NULL) OR ("char_length"("userinfo_url") <= 2048)))
);


ALTER TABLE "auth"."custom_oauth_providers" OWNER TO "supabase_auth_admin";


CREATE TABLE IF NOT EXISTS "auth"."flow_state" (
    "id" "uuid" NOT NULL,
    "user_id" "uuid",
    "auth_code" "text",
    "code_challenge_method" "auth"."code_challenge_method",
    "code_challenge" "text",
    "provider_type" "text" NOT NULL,
    "provider_access_token" "text",
    "provider_refresh_token" "text",
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone,
    "authentication_method" "text" NOT NULL,
    "auth_code_issued_at" timestamp with time zone,
    "invite_token" "text",
    "referrer" "text",
    "oauth_client_state_id" "uuid",
    "linking_target_id" "uuid",
    "email_optional" boolean DEFAULT false NOT NULL
);


ALTER TABLE "auth"."flow_state" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."flow_state" IS 'Stores metadata for all OAuth/SSO login flows';



CREATE TABLE IF NOT EXISTS "auth"."identities" (
    "provider_id" "text" NOT NULL,
    "user_id" "uuid" NOT NULL,
    "identity_data" "jsonb" NOT NULL,
    "provider" "text" NOT NULL,
    "last_sign_in_at" timestamp with time zone,
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone,
    "email" "text" GENERATED ALWAYS AS ("lower"(("identity_data" ->> 'email'::"text"))) STORED,
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL
);


ALTER TABLE "auth"."identities" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."identities" IS 'Auth: Stores identities associated to a user.';



COMMENT ON COLUMN "auth"."identities"."email" IS 'Auth: Email is a generated column that references the optional email property in the identity_data';



CREATE TABLE IF NOT EXISTS "auth"."instances" (
    "id" "uuid" NOT NULL,
    "uuid" "uuid",
    "raw_base_config" "text",
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone
);


ALTER TABLE "auth"."instances" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."instances" IS 'Auth: Manages users across multiple sites.';



CREATE TABLE IF NOT EXISTS "auth"."mfa_amr_claims" (
    "session_id" "uuid" NOT NULL,
    "created_at" timestamp with time zone NOT NULL,
    "updated_at" timestamp with time zone NOT NULL,
    "authentication_method" "text" NOT NULL,
    "id" "uuid" NOT NULL
);


ALTER TABLE "auth"."mfa_amr_claims" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."mfa_amr_claims" IS 'auth: stores authenticator method reference claims for multi factor authentication';



CREATE TABLE IF NOT EXISTS "auth"."mfa_challenges" (
    "id" "uuid" NOT NULL,
    "factor_id" "uuid" NOT NULL,
    "created_at" timestamp with time zone NOT NULL,
    "verified_at" timestamp with time zone,
    "ip_address" "inet" NOT NULL,
    "otp_code" "text",
    "web_authn_session_data" "jsonb"
);


ALTER TABLE "auth"."mfa_challenges" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."mfa_challenges" IS 'auth: stores metadata about challenge requests made';



CREATE TABLE IF NOT EXISTS "auth"."mfa_factors" (
    "id" "uuid" NOT NULL,
    "user_id" "uuid" NOT NULL,
    "friendly_name" "text",
    "factor_type" "auth"."factor_type" NOT NULL,
    "status" "auth"."factor_status" NOT NULL,
    "created_at" timestamp with time zone NOT NULL,
    "updated_at" timestamp with time zone NOT NULL,
    "secret" "text",
    "phone" "text",
    "last_challenged_at" timestamp with time zone,
    "web_authn_credential" "jsonb",
    "web_authn_aaguid" "uuid",
    "last_webauthn_challenge_data" "jsonb"
);


ALTER TABLE "auth"."mfa_factors" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."mfa_factors" IS 'auth: stores metadata about factors';



COMMENT ON COLUMN "auth"."mfa_factors"."last_webauthn_challenge_data" IS 'Stores the latest WebAuthn challenge data including attestation/assertion for customer verification';



CREATE TABLE IF NOT EXISTS "auth"."oauth_authorizations" (
    "id" "uuid" NOT NULL,
    "authorization_id" "text" NOT NULL,
    "client_id" "uuid" NOT NULL,
    "user_id" "uuid",
    "redirect_uri" "text" NOT NULL,
    "scope" "text" NOT NULL,
    "state" "text",
    "resource" "text",
    "code_challenge" "text",
    "code_challenge_method" "auth"."code_challenge_method",
    "response_type" "auth"."oauth_response_type" DEFAULT 'code'::"auth"."oauth_response_type" NOT NULL,
    "status" "auth"."oauth_authorization_status" DEFAULT 'pending'::"auth"."oauth_authorization_status" NOT NULL,
    "authorization_code" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "expires_at" timestamp with time zone DEFAULT ("now"() + '00:03:00'::interval) NOT NULL,
    "approved_at" timestamp with time zone,
    "nonce" "text",
    CONSTRAINT "oauth_authorizations_authorization_code_length" CHECK (("char_length"("authorization_code") <= 255)),
    CONSTRAINT "oauth_authorizations_code_challenge_length" CHECK (("char_length"("code_challenge") <= 128)),
    CONSTRAINT "oauth_authorizations_expires_at_future" CHECK (("expires_at" > "created_at")),
    CONSTRAINT "oauth_authorizations_nonce_length" CHECK (("char_length"("nonce") <= 255)),
    CONSTRAINT "oauth_authorizations_redirect_uri_length" CHECK (("char_length"("redirect_uri") <= 2048)),
    CONSTRAINT "oauth_authorizations_resource_length" CHECK (("char_length"("resource") <= 2048)),
    CONSTRAINT "oauth_authorizations_scope_length" CHECK (("char_length"("scope") <= 4096)),
    CONSTRAINT "oauth_authorizations_state_length" CHECK (("char_length"("state") <= 4096))
);


ALTER TABLE "auth"."oauth_authorizations" OWNER TO "supabase_auth_admin";


CREATE TABLE IF NOT EXISTS "auth"."oauth_client_states" (
    "id" "uuid" NOT NULL,
    "provider_type" "text" NOT NULL,
    "code_verifier" "text",
    "created_at" timestamp with time zone NOT NULL
);


ALTER TABLE "auth"."oauth_client_states" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."oauth_client_states" IS 'Stores OAuth states for third-party provider authentication flows where Supabase acts as the OAuth client.';



CREATE TABLE IF NOT EXISTS "auth"."oauth_clients" (
    "id" "uuid" NOT NULL,
    "client_secret_hash" "text",
    "registration_type" "auth"."oauth_registration_type" NOT NULL,
    "redirect_uris" "text" NOT NULL,
    "grant_types" "text" NOT NULL,
    "client_name" "text",
    "client_uri" "text",
    "logo_uri" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "deleted_at" timestamp with time zone,
    "client_type" "auth"."oauth_client_type" DEFAULT 'confidential'::"auth"."oauth_client_type" NOT NULL,
    "token_endpoint_auth_method" "text" NOT NULL,
    CONSTRAINT "oauth_clients_client_name_length" CHECK (("char_length"("client_name") <= 1024)),
    CONSTRAINT "oauth_clients_client_uri_length" CHECK (("char_length"("client_uri") <= 2048)),
    CONSTRAINT "oauth_clients_logo_uri_length" CHECK (("char_length"("logo_uri") <= 2048)),
    CONSTRAINT "oauth_clients_token_endpoint_auth_method_check" CHECK (("token_endpoint_auth_method" = ANY (ARRAY['client_secret_basic'::"text", 'client_secret_post'::"text", 'none'::"text"])))
);


ALTER TABLE "auth"."oauth_clients" OWNER TO "supabase_auth_admin";


CREATE TABLE IF NOT EXISTS "auth"."oauth_consents" (
    "id" "uuid" NOT NULL,
    "user_id" "uuid" NOT NULL,
    "client_id" "uuid" NOT NULL,
    "scopes" "text" NOT NULL,
    "granted_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "revoked_at" timestamp with time zone,
    CONSTRAINT "oauth_consents_revoked_after_granted" CHECK ((("revoked_at" IS NULL) OR ("revoked_at" >= "granted_at"))),
    CONSTRAINT "oauth_consents_scopes_length" CHECK (("char_length"("scopes") <= 2048)),
    CONSTRAINT "oauth_consents_scopes_not_empty" CHECK (("char_length"(TRIM(BOTH FROM "scopes")) > 0))
);


ALTER TABLE "auth"."oauth_consents" OWNER TO "supabase_auth_admin";


CREATE TABLE IF NOT EXISTS "auth"."one_time_tokens" (
    "id" "uuid" NOT NULL,
    "user_id" "uuid" NOT NULL,
    "token_type" "auth"."one_time_token_type" NOT NULL,
    "token_hash" "text" NOT NULL,
    "relates_to" "text" NOT NULL,
    "created_at" timestamp without time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp without time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "one_time_tokens_token_hash_check" CHECK (("char_length"("token_hash") > 0))
);


ALTER TABLE "auth"."one_time_tokens" OWNER TO "supabase_auth_admin";


CREATE TABLE IF NOT EXISTS "auth"."refresh_tokens" (
    "instance_id" "uuid",
    "id" bigint NOT NULL,
    "token" character varying(255),
    "user_id" character varying(255),
    "revoked" boolean,
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone,
    "parent" character varying(255),
    "session_id" "uuid"
);


ALTER TABLE "auth"."refresh_tokens" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."refresh_tokens" IS 'Auth: Store of tokens used to refresh JWT tokens once they expire.';



CREATE SEQUENCE IF NOT EXISTS "auth"."refresh_tokens_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "auth"."refresh_tokens_id_seq" OWNER TO "supabase_auth_admin";


ALTER SEQUENCE "auth"."refresh_tokens_id_seq" OWNED BY "auth"."refresh_tokens"."id";



CREATE TABLE IF NOT EXISTS "auth"."saml_providers" (
    "id" "uuid" NOT NULL,
    "sso_provider_id" "uuid" NOT NULL,
    "entity_id" "text" NOT NULL,
    "metadata_xml" "text" NOT NULL,
    "metadata_url" "text",
    "attribute_mapping" "jsonb",
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone,
    "name_id_format" "text",
    CONSTRAINT "entity_id not empty" CHECK (("char_length"("entity_id") > 0)),
    CONSTRAINT "metadata_url not empty" CHECK ((("metadata_url" = NULL::"text") OR ("char_length"("metadata_url") > 0))),
    CONSTRAINT "metadata_xml not empty" CHECK (("char_length"("metadata_xml") > 0))
);


ALTER TABLE "auth"."saml_providers" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."saml_providers" IS 'Auth: Manages SAML Identity Provider connections.';



CREATE TABLE IF NOT EXISTS "auth"."saml_relay_states" (
    "id" "uuid" NOT NULL,
    "sso_provider_id" "uuid" NOT NULL,
    "request_id" "text" NOT NULL,
    "for_email" "text",
    "redirect_to" "text",
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone,
    "flow_state_id" "uuid",
    CONSTRAINT "request_id not empty" CHECK (("char_length"("request_id") > 0))
);


ALTER TABLE "auth"."saml_relay_states" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."saml_relay_states" IS 'Auth: Contains SAML Relay State information for each Service Provider initiated login.';



CREATE TABLE IF NOT EXISTS "auth"."schema_migrations" (
    "version" character varying(255) NOT NULL
);


ALTER TABLE "auth"."schema_migrations" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."schema_migrations" IS 'Auth: Manages updates to the auth system.';



CREATE TABLE IF NOT EXISTS "auth"."sessions" (
    "id" "uuid" NOT NULL,
    "user_id" "uuid" NOT NULL,
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone,
    "factor_id" "uuid",
    "aal" "auth"."aal_level",
    "not_after" timestamp with time zone,
    "refreshed_at" timestamp without time zone,
    "user_agent" "text",
    "ip" "inet",
    "tag" "text",
    "oauth_client_id" "uuid",
    "refresh_token_hmac_key" "text",
    "refresh_token_counter" bigint,
    "scopes" "text",
    CONSTRAINT "sessions_scopes_length" CHECK (("char_length"("scopes") <= 4096))
);


ALTER TABLE "auth"."sessions" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."sessions" IS 'Auth: Stores session data associated to a user.';



COMMENT ON COLUMN "auth"."sessions"."not_after" IS 'Auth: Not after is a nullable column that contains a timestamp after which the session should be regarded as expired.';



COMMENT ON COLUMN "auth"."sessions"."refresh_token_hmac_key" IS 'Holds a HMAC-SHA256 key used to sign refresh tokens for this session.';



COMMENT ON COLUMN "auth"."sessions"."refresh_token_counter" IS 'Holds the ID (counter) of the last issued refresh token.';



CREATE TABLE IF NOT EXISTS "auth"."sso_domains" (
    "id" "uuid" NOT NULL,
    "sso_provider_id" "uuid" NOT NULL,
    "domain" "text" NOT NULL,
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone,
    CONSTRAINT "domain not empty" CHECK (("char_length"("domain") > 0))
);


ALTER TABLE "auth"."sso_domains" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."sso_domains" IS 'Auth: Manages SSO email address domain mapping to an SSO Identity Provider.';



CREATE TABLE IF NOT EXISTS "auth"."sso_providers" (
    "id" "uuid" NOT NULL,
    "resource_id" "text",
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone,
    "disabled" boolean,
    CONSTRAINT "resource_id not empty" CHECK ((("resource_id" = NULL::"text") OR ("char_length"("resource_id") > 0)))
);


ALTER TABLE "auth"."sso_providers" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."sso_providers" IS 'Auth: Manages SSO identity provider information; see saml_providers for SAML.';



COMMENT ON COLUMN "auth"."sso_providers"."resource_id" IS 'Auth: Uniquely identifies a SSO provider according to a user-chosen resource ID (case insensitive), useful in infrastructure as code.';



CREATE TABLE IF NOT EXISTS "auth"."users" (
    "instance_id" "uuid",
    "id" "uuid" NOT NULL,
    "aud" character varying(255),
    "role" character varying(255),
    "email" character varying(255),
    "encrypted_password" character varying(255),
    "email_confirmed_at" timestamp with time zone,
    "invited_at" timestamp with time zone,
    "confirmation_token" character varying(255),
    "confirmation_sent_at" timestamp with time zone,
    "recovery_token" character varying(255),
    "recovery_sent_at" timestamp with time zone,
    "email_change_token_new" character varying(255),
    "email_change" character varying(255),
    "email_change_sent_at" timestamp with time zone,
    "last_sign_in_at" timestamp with time zone,
    "raw_app_meta_data" "jsonb",
    "raw_user_meta_data" "jsonb",
    "is_super_admin" boolean,
    "created_at" timestamp with time zone,
    "updated_at" timestamp with time zone,
    "phone" "text" DEFAULT NULL::character varying,
    "phone_confirmed_at" timestamp with time zone,
    "phone_change" "text" DEFAULT ''::character varying,
    "phone_change_token" character varying(255) DEFAULT ''::character varying,
    "phone_change_sent_at" timestamp with time zone,
    "confirmed_at" timestamp with time zone GENERATED ALWAYS AS (LEAST("email_confirmed_at", "phone_confirmed_at")) STORED,
    "email_change_token_current" character varying(255) DEFAULT ''::character varying,
    "email_change_confirm_status" smallint DEFAULT 0,
    "banned_until" timestamp with time zone,
    "reauthentication_token" character varying(255) DEFAULT ''::character varying,
    "reauthentication_sent_at" timestamp with time zone,
    "is_sso_user" boolean DEFAULT false NOT NULL,
    "deleted_at" timestamp with time zone,
    "is_anonymous" boolean DEFAULT false NOT NULL,
    CONSTRAINT "users_email_change_confirm_status_check" CHECK ((("email_change_confirm_status" >= 0) AND ("email_change_confirm_status" <= 2)))
);


ALTER TABLE "auth"."users" OWNER TO "supabase_auth_admin";


COMMENT ON TABLE "auth"."users" IS 'Auth: Stores user login data within a secure schema.';



COMMENT ON COLUMN "auth"."users"."is_sso_user" IS 'Auth: Set this column to true when the account comes from SSO. These accounts can have duplicate emails.';



CREATE TABLE IF NOT EXISTS "public"."agenda_recursos" (
    "id" integer NOT NULL,
    "recurso_id" integer NOT NULL,
    "data_inicio" timestamp without time zone NOT NULL,
    "data_fim" timestamp without time zone NOT NULL,
    "tipo_agendamento" character varying(50),
    "descricao" "text",
    "dados_agendamento" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."agenda_recursos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."agenda_recursos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."agenda_recursos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."agenda_recursos_id_seq" OWNED BY "public"."agenda_recursos"."id";



CREATE TABLE IF NOT EXISTS "public"."logs_execucao_ia" (
    "id" bigint NOT NULL,
    "order_sn" "text" NOT NULL,
    "executed_at" timestamp with time zone DEFAULT "now"(),
    "input_data" "jsonb",
    "chat_context" "jsonb",
    "extracted_personalization" "jsonb",
    "model_result" "jsonb",
    "status" "text",
    "error_message" "text",
    "user_feedback_id" bigint,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb"
);


ALTER TABLE "public"."logs_execucao_ia" OWNER TO "postgres";


ALTER TABLE "public"."logs_execucao_ia" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."ai_execution_logs_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."cache_dashboard_pedidos" (
    "order_sn" "text" NOT NULL,
    "buyer_username" "text",
    "order_date" timestamp with time zone,
    "bling_number" "text",
    "items_summary" "jsonb",
    "has_chat" boolean DEFAULT false,
    "last_ai_status" "text",
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."cache_dashboard_pedidos" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."canais_venda" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "plataforma_id" integer,
    "descricao" "text",
    "configuracao" "jsonb",
    "ativo" boolean DEFAULT true,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "slug" character varying(100),
    "conta_bling_id" character varying(255),
    "horario_coleta" time without time zone,
    "flex" boolean DEFAULT false,
    "fulfillment" boolean DEFAULT false,
    "color" character varying(7) DEFAULT '#007bff'::character varying
);


ALTER TABLE "public"."canais_venda" OWNER TO "postgres";


COMMENT ON COLUMN "public"."canais_venda"."slug" IS 'URL-friendly identifier';



COMMENT ON COLUMN "public"."canais_venda"."conta_bling_id" IS 'Bling account ID';



COMMENT ON COLUMN "public"."canais_venda"."horario_coleta" IS 'Collection schedule';



COMMENT ON COLUMN "public"."canais_venda"."flex" IS 'Flexible delivery';



COMMENT ON COLUMN "public"."canais_venda"."fulfillment" IS 'Fulfillment service';



COMMENT ON COLUMN "public"."canais_venda"."color" IS 'Color for UI';



CREATE SEQUENCE IF NOT EXISTS "public"."canais_venda_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."canais_venda_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."canais_venda_id_seq" OWNED BY "public"."canais_venda"."id";



CREATE TABLE IF NOT EXISTS "public"."categoria_bom_regras" (
    "id" integer NOT NULL,
    "categoria_pai_id" integer NOT NULL,
    "nome_grupo" "text" NOT NULL,
    "categoria_componente_id" integer NOT NULL,
    "min_quantidade" numeric(10,2) DEFAULT 1,
    "max_quantidade" numeric(10,2) DEFAULT 1,
    "ordem" integer DEFAULT 0,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."categoria_bom_regras" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."categoria_bom_regras_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."categoria_bom_regras_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."categoria_bom_regras_id_seq" OWNED BY "public"."categoria_bom_regras"."id";



CREATE TABLE IF NOT EXISTS "public"."categorias" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" "text",
    "categoria_pai_id" integer,
    "nivel" integer DEFAULT 0,
    "caminho" "text",
    "ativo" boolean DEFAULT true,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "comercializavel" boolean DEFAULT false,
    "componente" boolean DEFAULT false
);


ALTER TABLE "public"."categorias" OWNER TO "postgres";


COMMENT ON COLUMN "public"."categorias"."comercializavel" IS 'Indica se os produtos desta categoria podem ser comercializados (associados em vendas, etc)';



COMMENT ON COLUMN "public"."categorias"."componente" IS 'Indica se os produtos desta categoria podem ser adicionados como componentes na lista de materiais de outros produtos';



CREATE SEQUENCE IF NOT EXISTS "public"."categorias_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."categorias_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."categorias_id_seq" OWNED BY "public"."categorias"."id";



CREATE TABLE IF NOT EXISTS "public"."componentes_ordem_producao" (
    "id" integer NOT NULL,
    "ordem_producao_id" integer NOT NULL,
    "componente_id" integer,
    "sku" character varying(100),
    "descricao" character varying(500),
    "quantidade_necessaria" integer,
    "quantidade_utilizada" integer DEFAULT 0,
    "status" character varying(50) DEFAULT 'PENDENTE'::character varying,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."componentes_ordem_producao" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."componentes_ordem_producao_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."componentes_ordem_producao_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."componentes_ordem_producao_id_seq" OWNED BY "public"."componentes_ordem_producao"."id";



CREATE TABLE IF NOT EXISTS "public"."configuracoes_aplicacao" (
    "id" integer NOT NULL,
    "nome" character varying(255) NOT NULL,
    "valor" "jsonb" NOT NULL,
    "descricao" "text",
    "categoria" character varying(100),
    "protegido" boolean DEFAULT false,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "tipo_valor" character varying(50) DEFAULT 'json'::character varying,
    "entidade_tipo" character varying(50),
    "entidade_id" integer,
    "migrada_de_json" boolean DEFAULT false,
    "atualizado_em" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "chk_entidade_consistency" CHECK (((("entidade_tipo" IS NULL) AND ("entidade_id" IS NULL)) OR (("entidade_tipo" IS NOT NULL) AND ("entidade_id" IS NOT NULL)))),
    CONSTRAINT "chk_nome_not_empty" CHECK ((("nome" IS NULL) OR ("length"(TRIM(BOTH FROM "nome")) > 0)))
);


ALTER TABLE "public"."configuracoes_aplicacao" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."configuracoes_aplicacao_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."configuracoes_aplicacao_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."configuracoes_aplicacao_id_seq" OWNED BY "public"."configuracoes_aplicacao"."id";



CREATE TABLE IF NOT EXISTS "public"."contas_bling" (
    "id" character varying NOT NULL,
    "nome" character varying(255) NOT NULL,
    "api_key" character varying(255),
    "endpoint" character varying(500),
    "ativa" boolean DEFAULT true,
    "dados_autenticacao" "jsonb",
    "ultima_verificacao" timestamp without time zone,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "cnpj" character varying,
    "client_id" character varying,
    "client_secret" character varying,
    "access_token" character varying,
    "refresh_token" character varying,
    "expires_in" integer,
    "platform_name" character varying,
    "icon_url" character varying,
    "instance_name" character varying,
    "versao_api" character varying
);


ALTER TABLE "public"."contas_bling" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."contas_bling_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."contas_bling_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."contas_bling_id_seq" OWNED BY "public"."contas_bling"."id";



CREATE TABLE IF NOT EXISTS "public"."conversoes_uom_produto" (
    "id" integer NOT NULL,
    "produto_id" integer NOT NULL,
    "unidade_origem_id" integer NOT NULL,
    "unidade_destino_id" integer NOT NULL,
    "fator_conversao" numeric(15,6),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."conversoes_uom_produto" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."conversoes_uom_produto_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."conversoes_uom_produto_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."conversoes_uom_produto_id_seq" OWNED BY "public"."conversoes_uom_produto"."id";



CREATE TABLE IF NOT EXISTS "public"."demandas_item_origem" (
    "id" integer NOT NULL,
    "demanda_item_id" integer NOT NULL,
    "plataforma" character varying(50) NOT NULL,
    "pedido_externo_id" character varying(255) NOT NULL,
    "item_externo_id" character varying(255),
    "sku_externo" character varying(255) NOT NULL,
    "quantidade_atendida" integer NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."demandas_item_origem" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."demandas_item_origem_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."demandas_item_origem_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."demandas_item_origem_id_seq" OWNED BY "public"."demandas_item_origem"."id";



CREATE TABLE IF NOT EXISTS "public"."demandas_producao" (
    "id" integer NOT NULL,
    "demanda_id" character varying(255) NOT NULL,
    "descricao" "text",
    "produto_id" integer,
    "quantidade" integer,
    "data_entrega" "date",
    "prioridade" integer DEFAULT 0,
    "status" character varying(50) DEFAULT 'PENDENTE'::character varying,
    "responsavel_id" integer,
    "dados_adicionais" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "canal_venda_id" integer,
    "horario_coleta" time without time zone,
    "tipo_demanda" character varying(50),
    "observacoes" "text",
    "prioridade_manual" integer DEFAULT 0,
    "pedido_numero" character varying(100),
    "data_conclusao" timestamp without time zone,
    "is_flex" boolean DEFAULT false,
    "fulfillment" boolean DEFAULT false,
    "modalidade_logistica" character varying(20),
    "classificacao_cliente" character varying(10),
    "capacidade_requerida" "jsonb" DEFAULT '{}'::"jsonb",
    "categoria_demanda" "text",
    "prioridade_tipo" "text",
    "data_limite_execucao" "date",
    "data_inicio_planejada" timestamp with time zone,
    "data_fim_planejada" timestamp with time zone,
    "setores_envolvidos" "jsonb",
    "categoria_temporal" "text",
    "data_promessa_cliente" "date",
    "data_maxima_entrega" "date"
);


ALTER TABLE "public"."demandas_producao" OWNER TO "postgres";


COMMENT ON COLUMN "public"."demandas_producao"."tipo_demanda" IS 'Tipo de demanda: PLATAFORMA (venda consolidada), B2B (venda corporativa), FULFILLMENT (reposição para fulfillment), ESTOQUE_INTERNO (produção para estoque interno)';



COMMENT ON COLUMN "public"."demandas_producao"."modalidade_logistica" IS 'Modalidade logística: STANDARD (Padrão), EXPRESS (Flex/Urgente), FULFILLMENT (Armazém Externo), RETIRADA (Local)';



COMMENT ON COLUMN "public"."demandas_producao"."classificacao_cliente" IS 'Classificação do cliente: B2C (Varejo), B2B (Corporativo), INTERNO (Estoque/Amostra)';



COMMENT ON COLUMN "public"."demandas_producao"."capacidade_requerida" IS 'Capacidade requerida para a produção da demanda, segmentada por setor/turno';



CREATE SEQUENCE IF NOT EXISTS "public"."demandas_producao_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."demandas_producao_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."demandas_producao_id_seq" OWNED BY "public"."demandas_producao"."id";



CREATE TABLE IF NOT EXISTS "public"."depositos" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" "text",
    "endereco" "jsonb",
    "capacidade" numeric(15,2),
    "capacidade_utilizada" numeric(15,2) DEFAULT 0,
    "tipo" character varying(50),
    "ativo" boolean DEFAULT true,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "is_default" boolean DEFAULT false
);


ALTER TABLE "public"."depositos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."depositos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."depositos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."depositos_id_seq" OWNED BY "public"."depositos"."id";



CREATE TABLE IF NOT EXISTS "public"."entrega_producao" (
    "id" "text" NOT NULL,
    "item_demanda_id" integer,
    "demanda_id" integer NOT NULL,
    "quantidade" integer NOT NULL,
    "data_entrega" "date" NOT NULL,
    "user_id" "text",
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."entrega_producao" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."estoque_atual" (
    "id" integer NOT NULL,
    "produto_id" integer NOT NULL,
    "deposito_id" integer NOT NULL,
    "saldo_atual" numeric(15,4) DEFAULT 0,
    "nivel_minimo" numeric(15,4) DEFAULT 0,
    "nivel_maximo" numeric(15,4),
    "reservado" numeric(15,4) DEFAULT 0,
    "ultima_atualizacao" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "disponivel" numeric(15,4) GENERATED ALWAYS AS (("saldo_atual" - "reservado")) STORED
);


ALTER TABLE "public"."estoque_atual" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."estoque_atual_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."estoque_atual_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."estoque_atual_id_seq" OWNED BY "public"."estoque_atual"."id";



CREATE TABLE IF NOT EXISTS "public"."eventos_auditoria" (
    "id" integer NOT NULL,
    "tipo_evento" character varying(100) NOT NULL,
    "descricao" "text",
    "usuario_id" integer,
    "entidade_afetada" character varying(100),
    "registro_id" integer,
    "dados_anteriores" "jsonb",
    "dados_novos" "jsonb",
    "ip_origem" "inet",
    "user_agent" "text",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."eventos_auditoria" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."eventos_auditoria_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."eventos_auditoria_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."eventos_auditoria_id_seq" OWNED BY "public"."eventos_auditoria"."id";



CREATE TABLE IF NOT EXISTS "public"."feedback_pedido" (
    "id" integer NOT NULL,
    "codigo_pedido" character varying(255) NOT NULL,
    "texto_feedback" "text",
    "avaliacao" integer,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "feedback_pedido_avaliacao_check" CHECK ((("avaliacao" >= 1) AND ("avaliacao" <= 5)))
);


ALTER TABLE "public"."feedback_pedido" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."feedback_pedido_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."feedback_pedido_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."feedback_pedido_id_seq" OWNED BY "public"."feedback_pedido"."id";



CREATE TABLE IF NOT EXISTS "public"."feedbacks_execucao_ia" (
    "id" bigint NOT NULL,
    "order_sn" "text" NOT NULL,
    "feedback" smallint NOT NULL,
    "feedback_notes" "text",
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."feedbacks_execucao_ia" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."feedbacks_negativo" (
    "id" bigint NOT NULL,
    "order_sn" "text" NOT NULL,
    "order_data" "jsonb",
    "messages_data" "jsonb",
    "execution_logs" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."feedbacks_negativo" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."ficha_tecnica" (
    "id" integer NOT NULL,
    "produto_pai_id" integer,
    "componente_id" integer,
    "quantidade_necessaria" numeric(15,6) DEFAULT 1 NOT NULL,
    "unidade_medida" character varying(50) DEFAULT 'un'::character varying,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "sku_produto_pai" character varying(100),
    "sku_componente" character varying(100)
);


ALTER TABLE "public"."ficha_tecnica" OWNER TO "postgres";


COMMENT ON COLUMN "public"."ficha_tecnica"."sku_produto_pai" IS 'SKU do produto pai para facilitar migração e estabilidade';



COMMENT ON COLUMN "public"."ficha_tecnica"."sku_componente" IS 'SKU do componente';



CREATE SEQUENCE IF NOT EXISTS "public"."ficha_tecnica_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."ficha_tecnica_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."ficha_tecnica_id_seq" OWNED BY "public"."ficha_tecnica"."id";



CREATE TABLE IF NOT EXISTS "public"."fornecedor_insumos" (
    "id" integer NOT NULL,
    "fornecedor_id" integer NOT NULL,
    "produto_id" integer NOT NULL,
    "lead_time_dias" integer DEFAULT 0,
    "moq" numeric(10,2) DEFAULT 0.0,
    "unidade_compra" character varying(20),
    "preco_ultima_compra" numeric(10,4),
    "moeda" character varying(10) DEFAULT 'BRL'::character varying,
    "codigo_no_fornecedor" character varying(100),
    "link_produto_fornecedor" "text",
    "preferencial" boolean DEFAULT false,
    "created_at" timestamp without time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp without time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."fornecedor_insumos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."fornecedor_insumos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."fornecedor_insumos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."fornecedor_insumos_id_seq" OWNED BY "public"."fornecedor_insumos"."id";



CREATE TABLE IF NOT EXISTS "public"."fornecedores" (
    "id" integer NOT NULL,
    "nome" character varying(255) NOT NULL,
    "cnpj" character varying(20),
    "contato_principal" "text",
    "informacoes_contato" "jsonb",
    "categoria" character varying(100),
    "classificacao" integer,
    "ativo" boolean DEFAULT true,
    "dados_contratuais" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "fornecedores_classificacao_check" CHECK ((("classificacao" >= 1) AND ("classificacao" <= 5)))
);


ALTER TABLE "public"."fornecedores" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."fornecedores_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."fornecedores_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."fornecedores_id_seq" OWNED BY "public"."fornecedores"."id";



CREATE TABLE IF NOT EXISTS "public"."grupo_mensagens_chat_shopee" (
    "event_id" "text" NOT NULL,
    "msg_id" "text" NOT NULL
);


ALTER TABLE "public"."grupo_mensagens_chat_shopee" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."identificadores_alternativos" (
    "id" integer NOT NULL,
    "produto_id" integer NOT NULL,
    "tipo_identificador" character varying(50) NOT NULL,
    "valor_identificador" character varying(255) NOT NULL,
    "criado_em" timestamp with time zone DEFAULT "now"(),
    "atualizado_em" timestamp with time zone DEFAULT "now"(),
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "chk_tipo_identificador" CHECK ((("tipo_identificador")::"text" = ANY ((ARRAY['sku'::character varying, 'nome'::character varying, 'id'::character varying])::"text"[])))
);


ALTER TABLE "public"."identificadores_alternativos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."identificadores_alternativos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."identificadores_alternativos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."identificadores_alternativos_id_seq" OWNED BY "public"."identificadores_alternativos"."id";



CREATE TABLE IF NOT EXISTS "public"."installed_integrations" (
    "id" integer NOT NULL,
    "module_id" character varying(100) NOT NULL,
    "instance_name" character varying(255) NOT NULL,
    "user_id" character varying(255),
    "config" "jsonb" DEFAULT '{}'::"jsonb",
    "access_token" "text",
    "refresh_token" "text",
    "expires_at" timestamp with time zone,
    "is_active" boolean DEFAULT true,
    "last_sync" timestamp with time zone,
    "sync_status" character varying(50) DEFAULT 'pending'::character varying,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "credentials" "jsonb" DEFAULT '{}'::"jsonb",
    "last_refresh_attempt" timestamp with time zone,
    "refresh_error" "text"
);


ALTER TABLE "public"."installed_integrations" OWNER TO "postgres";


COMMENT ON COLUMN "public"."installed_integrations"."credentials" IS 'Platform-specific metadata and raw responses';



COMMENT ON COLUMN "public"."installed_integrations"."last_refresh_attempt" IS 'Timestamp of the last token refresh attempt';



COMMENT ON COLUMN "public"."installed_integrations"."refresh_error" IS 'Error message from the last failed refresh attempt';



CREATE SEQUENCE IF NOT EXISTS "public"."installed_integrations_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."installed_integrations_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."installed_integrations_id_seq" OWNED BY "public"."installed_integrations"."id";



CREATE TABLE IF NOT EXISTS "public"."integration_modules" (
    "id" "text" NOT NULL,
    "name" "text" NOT NULL,
    "description" "text",
    "version" "text",
    "author" "text",
    "icon_url" "text",
    "category" "text",
    "tags" "text"[],
    "is_active" boolean DEFAULT true,
    "config_schema" "jsonb" DEFAULT '{}'::"jsonb",
    "auth_flow" "text",
    "auth_config" "jsonb" DEFAULT '{}'::"jsonb",
    "data_mapping_spec" "jsonb" DEFAULT '{}'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL
);


ALTER TABLE "public"."integration_modules" OWNER TO "postgres";


COMMENT ON TABLE "public"."integration_modules" IS 'Available integration modules for the marketplace';



CREATE TABLE IF NOT EXISTS "public"."integration_refresh_logs" (
    "id" integer NOT NULL,
    "integration_id" integer NOT NULL,
    "status" character varying(50) NOT NULL,
    "message" "text",
    "execution_mode" character varying(50) DEFAULT 'scheduled'::character varying,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."integration_refresh_logs" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."integration_refresh_logs_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."integration_refresh_logs_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."integration_refresh_logs_id_seq" OWNED BY "public"."integration_refresh_logs"."id";



CREATE TABLE IF NOT EXISTS "public"."itens_demanda" (
    "id" integer NOT NULL,
    "demanda_id" integer NOT NULL,
    "produto_id" integer,
    "sku" character varying(100),
    "descricao" character varying(500),
    "quantidade" numeric(15,4),
    "dados_adicionais" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "capas_impressas_qtd" numeric(15,4) DEFAULT 0,
    "capas_produzidas_qtd" numeric(15,4) DEFAULT 0,
    "capas_prontas_retirada_qtd" numeric(15,4) DEFAULT 0,
    "miolos_prontos_retirada_qtd" numeric(15,4) DEFAULT 0,
    "expedicao_capas_retiradas_qtd" numeric(15,4) DEFAULT 0,
    "expedicao_miolos_retirados_qtd" numeric(15,4) DEFAULT 0,
    "status_item" character varying(50) DEFAULT 'Pendente'::character varying,
    "miolo_nome" character varying(255),
    "variacao" character varying(255),
    "id_produto_miolo" integer
);


ALTER TABLE "public"."itens_demanda" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."itens_demanda_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."itens_demanda_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."itens_demanda_id_seq" OWNED BY "public"."itens_demanda"."id";



CREATE TABLE IF NOT EXISTS "public"."itens_ordem_compra" (
    "id" integer NOT NULL,
    "ordem_compra_id" integer NOT NULL,
    "produto_id" integer,
    "sku" character varying(100),
    "descricao" character varying(500),
    "quantidade" integer,
    "preco_unitario" numeric(10,2),
    "subtotal" numeric(10,2),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."itens_ordem_compra" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."itens_ordem_compra_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."itens_ordem_compra_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."itens_ordem_compra_id_seq" OWNED BY "public"."itens_ordem_compra"."id";



CREATE TABLE IF NOT EXISTS "public"."itens_pedido" (
    "id" integer NOT NULL,
    "pedido_id" integer,
    "produto_id" integer,
    "sku_externo" character varying(100),
    "descricao" character varying(500),
    "quantidade" numeric(10,4),
    "preco_unitario" numeric(15,2),
    "subtotal" numeric(15,2),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."itens_pedido" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."itens_pedido_bling" (
    "id" integer NOT NULL,
    "pedido_bling_id" integer,
    "sku" character varying(255),
    "descricao" character varying(500),
    "quantidade" integer,
    "preco_unitario" numeric(10,2),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "codigo" character varying(100),
    "unidade" character varying(20),
    "valor" numeric(10,2),
    "personalizado" boolean DEFAULT false,
    "produto" "jsonb",
    "criado_em" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "bling_item_id" bigint,
    "atualizado_em" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."itens_pedido_bling" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."itens_pedido_bling_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."itens_pedido_bling_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."itens_pedido_bling_id_seq" OWNED BY "public"."itens_pedido_bling"."id";



CREATE SEQUENCE IF NOT EXISTS "public"."itens_pedido_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."itens_pedido_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."itens_pedido_id_seq" OWNED BY "public"."itens_pedido"."id";



CREATE TABLE IF NOT EXISTS "public"."itens_venda" (
    "id" integer NOT NULL,
    "venda_id" integer NOT NULL,
    "produto_id" integer,
    "sku" character varying(100),
    "descricao" character varying(500),
    "quantidade" integer,
    "preco_unitario" numeric(10,2),
    "subtotal" numeric(10,2),
    "personalizacao" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."itens_venda" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."itens_venda_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."itens_venda_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."itens_venda_id_seq" OWNED BY "public"."itens_venda"."id";



CREATE TABLE IF NOT EXISTS "public"."logs_producao_diaria" (
    "id" integer NOT NULL,
    "data" "date",
    "turno" character varying(50),
    "equipe_id" integer,
    "resumo_diario" "jsonb",
    "detalhes_producao" "jsonb",
    "problemas" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "data_registro" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "produto_id" integer,
    "produto_nome" character varying(255),
    "quantidade_produzida" numeric(15,4) DEFAULT 0,
    "ordem_producao_id" integer,
    "snapshot_estoque_componentes" "jsonb" DEFAULT '[]'::"jsonb",
    "user_email" character varying(255),
    "deleted" boolean DEFAULT false,
    "deleted_at" timestamp without time zone,
    "deleted_by" character varying(255)
);


ALTER TABLE "public"."logs_producao_diaria" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."logs_producao_diaria_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."logs_producao_diaria_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."logs_producao_diaria_id_seq" OWNED BY "public"."logs_producao_diaria"."id";



CREATE TABLE IF NOT EXISTS "public"."mensagem_chat_shopee" (
    "id" "text" NOT NULL,
    "shop_id" bigint,
    "request_id" "text",
    "from_id" bigint,
    "to_id" bigint,
    "from_shop_id" bigint,
    "to_shop_id" bigint,
    "from_user_name" "text",
    "to_user_name" "text",
    "type" "text",
    "conversation_id" bigint,
    "faq_session_id" bigint,
    "source_type" "text",
    "created_timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "created_at" timestamp without time zone,
    "status" "text",
    "message_option" integer,
    "source" "text",
    "content" "jsonb",
    "faq_info" "jsonb",
    "source_content" "jsonb",
    "raw_json" "jsonb",
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."mensagem_chat_shopee" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."movimentacoes_estoque" (
    "id" integer NOT NULL,
    "produto_id" integer NOT NULL,
    "deposito_id" integer NOT NULL,
    "tipo_movimentacao" character varying(50) NOT NULL,
    "quantidade" numeric(15,4) NOT NULL,
    "saldo_antes" numeric(15,4),
    "saldo_depois" numeric(15,4),
    "documento_referencia" character varying(255),
    "motivo" "text",
    "usuario_id" integer,
    "data_movimentacao" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."movimentacoes_estoque" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."movimentacoes_estoque_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."movimentacoes_estoque_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."movimentacoes_estoque_id_seq" OWNED BY "public"."movimentacoes_estoque"."id";



ALTER TABLE "public"."feedbacks_negativo" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."negative_feedback_snapshots_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."notificacoes" (
    "id" integer NOT NULL,
    "titulo" character varying(255) NOT NULL,
    "mensagem" "text" NOT NULL,
    "tipo" character varying(50),
    "nivel_critica" character varying(20) DEFAULT 'MEDIA'::character varying,
    "destinatarios" "jsonb",
    "lida" boolean DEFAULT false,
    "data_envio" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "data_visualizacao" timestamp without time zone,
    "dados_adicionais" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."notificacoes" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."notificacoes_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."notificacoes_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."notificacoes_id_seq" OWNED BY "public"."notificacoes"."id";



CREATE TABLE IF NOT EXISTS "public"."ordens_compra" (
    "id" integer NOT NULL,
    "ordem_compra_id" character varying(255) NOT NULL,
    "numero_ordem" character varying(100),
    "fornecedor_id" integer,
    "status" character varying(50) DEFAULT 'PENDENTE'::character varying,
    "data_emissao" "date",
    "data_entrega_prevista" "date",
    "valor_total" numeric(10,2),
    "dados_adicionais" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."ordens_compra" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."ordens_compra_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."ordens_compra_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."ordens_compra_id_seq" OWNED BY "public"."ordens_compra"."id";



CREATE TABLE IF NOT EXISTS "public"."ordens_producao" (
    "id" integer NOT NULL,
    "ordem_id" character varying(255) NOT NULL,
    "numero_ordem" character varying(100),
    "produto_id" integer,
    "sku" character varying(100),
    "descricao" "text",
    "quantidade" numeric(15,4),
    "status" character varying(50) DEFAULT 'PENDENTE'::character varying,
    "data_inicio" "date",
    "data_fim" "date",
    "prioridade" integer DEFAULT 0,
    "responsavel_id" integer,
    "dados_adicionais" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "quantidade_produzida" numeric(15,4) DEFAULT 0,
    "data_finalizacao_prevista" timestamp without time zone
);


ALTER TABLE "public"."ordens_producao" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."ordens_producao_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."ordens_producao_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."ordens_producao_id_seq" OWNED BY "public"."ordens_producao"."id";



ALTER TABLE "public"."feedbacks_execucao_ia" ALTER COLUMN "id" ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME "public"."order_feedback_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);



CREATE TABLE IF NOT EXISTS "public"."pedidos" (
    "id" integer NOT NULL,
    "uuid_pedido" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "numero_pedido" character varying(50) NOT NULL,
    "codigo_pedido_externo" character varying(100) NOT NULL,
    "origem" character varying(50) NOT NULL,
    "informacoes_cliente" "jsonb" NOT NULL,
    "situacao_pedido_id" integer,
    "total_pedido" numeric(15,2),
    "moeda" character varying(10) DEFAULT 'BRL'::character varying,
    "data_venda" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "cliente_nome" character varying(255),
    "cliente_documento" character varying(20)
);


ALTER TABLE "public"."pedidos" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."pedidos_bling" (
    "id" integer NOT NULL,
    "numero_pedido" character varying(255) NOT NULL,
    "loja_id" integer,
    "situacao_pedido" character varying(100),
    "data_pedido" "date",
    "valor_total" numeric(10,2),
    "nome_cliente" character varying(255),
    "email_cliente" character varying(255),
    "telefone_cliente" character varying(50),
    "endereco_entrega" "jsonb",
    "itens" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "contato" "text",
    "personalizado" boolean DEFAULT false,
    "bling_id" bigint,
    "deletado" boolean DEFAULT false,
    "criado_em" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "atualizado_em" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "numero_loja" "text"
);


ALTER TABLE "public"."pedidos_bling" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."pedidos_bling_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pedidos_bling_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pedidos_bling_id_seq" OWNED BY "public"."pedidos_bling"."id";



CREATE SEQUENCE IF NOT EXISTS "public"."pedidos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pedidos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pedidos_id_seq" OWNED BY "public"."pedidos"."id";



CREATE TABLE IF NOT EXISTS "public"."pedidos_shopee" (
    "id" integer NOT NULL,
    "codigo_pedido" character varying(255) NOT NULL,
    "id_pedido_shopee" bigint,
    "status_pedido" character varying(100),
    "valor_total" numeric(10,2),
    "moeda" character varying(10),
    "data_criacao" timestamp without time zone,
    "data_atualizacao" timestamp without time zone,
    "data_pagamento" timestamp without time zone,
    "dias_para_envio" integer,
    "data_envio" timestamp without time zone,
    "endereco_entrega" "jsonb",
    "itens_pedido" "jsonb",
    "informacoes_comprador" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "mensagem" "text"
);


ALTER TABLE "public"."pedidos_shopee" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."pedidos_shopee_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pedidos_shopee_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pedidos_shopee_id_seq" OWNED BY "public"."pedidos_shopee"."id";



CREATE TABLE IF NOT EXISTS "public"."permissoes_setor" (
    "id" integer NOT NULL,
    "setor_id" integer NOT NULL,
    "recurso_id" integer NOT NULL,
    "pode_ler" boolean DEFAULT false NOT NULL,
    "pode_criar" boolean DEFAULT false NOT NULL,
    "pode_editar" boolean DEFAULT false NOT NULL,
    "pode_excluir" boolean DEFAULT false NOT NULL,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."permissoes_setor" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."permissoes_setor_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."permissoes_setor_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."permissoes_setor_id_seq" OWNED BY "public"."permissoes_setor"."id";



CREATE TABLE IF NOT EXISTS "public"."personalizacoes_pedido" (
    "id" integer NOT NULL,
    "codigo_pedido" character varying(255) NOT NULL,
    "dados_cliente" "jsonb",
    "detalhes_personalizacao" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "shopee_order_sn" "text",
    "bling_id" "text",
    "item_id" "text",
    "item_description" "text",
    "customization_name" "text",
    "customization_initial" "text",
    "status" "text",
    "reasoning" "text",
    "name_source_message_id" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb"
);


ALTER TABLE "public"."personalizacoes_pedido" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."personalizacoes_pedido_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."personalizacoes_pedido_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."personalizacoes_pedido_id_seq" OWNED BY "public"."personalizacoes_pedido"."id";



CREATE TABLE IF NOT EXISTS "public"."plataformas" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" "text",
    "tipo" character varying(50),
    "ativa" boolean DEFAULT true,
    "configuracao" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."plataformas" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."plataformas_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."plataformas_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."plataformas_id_seq" OWNED BY "public"."plataformas"."id";



CREATE TABLE IF NOT EXISTS "public"."pontos_coleta" (
    "id" integer NOT NULL,
    "nome" character varying(255) NOT NULL,
    "horario_corte_padrao" time without time zone NOT NULL,
    "endereco" "text",
    "ativo" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."pontos_coleta" OWNER TO "postgres";


COMMENT ON TABLE "public"."pontos_coleta" IS 'Locais físicos para despacho de mercadorias (Agências, Pontos de Coleta, etc)';



COMMENT ON COLUMN "public"."pontos_coleta"."horario_corte_padrao" IS 'Horário limite padrão para entrega de mercadorias neste ponto';



CREATE SEQUENCE IF NOT EXISTS "public"."pontos_coleta_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."pontos_coleta_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."pontos_coleta_id_seq" OWNED BY "public"."pontos_coleta"."id";



CREATE TABLE IF NOT EXISTS "public"."print_jobs" (
    "id" integer NOT NULL,
    "demanda_item_id" integer,
    "product_id" integer,
    "artwork_id" integer,
    "tipo_arquivo" character varying(50),
    "status" character varying(50) DEFAULT 'pendente'::character varying,
    "impressora_alvo" character varying(255),
    "tentativas" integer DEFAULT 0,
    "logs" "text",
    "created_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "timezone"('utc'::"text", "now"()) NOT NULL,
    "quantidade" integer DEFAULT 1
);


ALTER TABLE "public"."print_jobs" OWNER TO "postgres";


COMMENT ON COLUMN "public"."print_jobs"."quantidade" IS 'Quantidade de cópias a serem impressas neste job';



CREATE SEQUENCE IF NOT EXISTS "public"."print_jobs_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."print_jobs_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."print_jobs_id_seq" OWNED BY "public"."print_jobs"."id";



CREATE TABLE IF NOT EXISTS "public"."product_artworks" (
    "id" integer NOT NULL,
    "product_id" integer NOT NULL,
    "filename" character varying NOT NULL,
    "original_filename" character varying NOT NULL,
    "file_path" character varying NOT NULL,
    "file_size" integer,
    "mime_type" character varying,
    "upload_date" timestamp without time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."product_artworks" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."product_artworks_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."product_artworks_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."product_artworks_id_seq" OWNED BY "public"."product_artworks"."id";



CREATE TABLE IF NOT EXISTS "public"."produtos" (
    "id" integer NOT NULL,
    "nome" character varying(255) NOT NULL,
    "sku" character varying(100) NOT NULL,
    "descricao" "text",
    "categoria_id" integer,
    "tags" "text"[],
    "atributos" "jsonb",
    "precificacao" "jsonb",
    "dados_estoque" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "preco_custo" numeric(10,4),
    "preco_venda" numeric(10,4),
    "estoque_minimo" integer DEFAULT 0,
    "estoque_maximo" integer DEFAULT 0,
    "tipo_material" character varying(50),
    "unidade_medida_id" integer,
    "sku_pai" character varying(100),
    "parent_id" integer,
    "status" character varying(20) DEFAULT 'ativo'::character varying,
    "formato" "text" DEFAULT 'simples'::"text",
    "herdar_dados_pai" boolean DEFAULT true,
    "herdar_bom_pai" boolean DEFAULT true,
    "setor_responsavel_id" integer,
    "estoque_seguranca_dias" integer DEFAULT 0,
    "ponto_ressuprimento" numeric(10,4),
    "lote_economico" numeric(10,4),
    "curva_abc" character varying(1)
);


ALTER TABLE "public"."produtos" OWNER TO "postgres";


COMMENT ON COLUMN "public"."produtos"."preco_custo" IS 'Preço de custo do produto (normalizado de precificacao.cost_price)';



COMMENT ON COLUMN "public"."produtos"."preco_venda" IS 'Preço de venda do produto (normalizado de precificacao.price)';



COMMENT ON COLUMN "public"."produtos"."estoque_minimo" IS 'Estoque mínimo desejado (normalizado de dados_estoque.stock_min)';



COMMENT ON COLUMN "public"."produtos"."estoque_maximo" IS 'Estoque máximo permitido (normalizado de dados_estoque.stock_max)';



COMMENT ON COLUMN "public"."produtos"."tipo_material" IS 'Tipo de material do produto (normalizado de atributos.material_type)';



COMMENT ON COLUMN "public"."produtos"."unidade_medida_id" IS 'Referência para unidade de medida (normalizado de atributos.unit_of_measure_id)';



COMMENT ON COLUMN "public"."produtos"."sku_pai" IS 'SKU do produto pai para produtos componentes em BOM';



COMMENT ON COLUMN "public"."produtos"."status" IS 'Status do produto (ativo, inativo, rascunho, etc.)';



CREATE TABLE IF NOT EXISTS "public"."produtos_externos" (
    "id" integer NOT NULL,
    "produto_id" integer NOT NULL,
    "codigo_externo" character varying(255) NOT NULL,
    "plataforma" character varying(50) NOT NULL,
    "metadados" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."produtos_externos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."produtos_externos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."produtos_externos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."produtos_externos_id_seq" OWNED BY "public"."produtos_externos"."id";



CREATE SEQUENCE IF NOT EXISTS "public"."produtos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."produtos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."produtos_id_seq" OWNED BY "public"."produtos"."id";



CREATE TABLE IF NOT EXISTS "public"."recursos" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" character varying(255),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."recursos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."recursos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."recursos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."recursos_id_seq" OWNED BY "public"."recursos"."id";



CREATE TABLE IF NOT EXISTS "public"."recursos_produtivos" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "tipo" character varying(50),
    "descricao" "text",
    "capacidade" "jsonb",
    "status" character varying(50) DEFAULT 'ATIVO'::character varying,
    "dados_tecnicos" "jsonb",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."recursos_produtivos" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."recursos_produtivos_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."recursos_produtivos_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."recursos_produtivos_id_seq" OWNED BY "public"."recursos_produtivos"."id";



CREATE TABLE IF NOT EXISTS "public"."regras_logisticas_canal" (
    "id" integer NOT NULL,
    "canal_venda_id" integer NOT NULL,
    "modalidade" character varying(50) NOT NULL,
    "tipo_envio" character varying(50) NOT NULL,
    "horario_limite" time without time zone NOT NULL,
    "ponto_coleta_id" integer,
    "prioridade_uso" integer DEFAULT 1,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."regras_logisticas_canal" OWNER TO "postgres";


COMMENT ON TABLE "public"."regras_logisticas_canal" IS 'Regras de janelas de despacho e backups por canal e modalidade';



COMMENT ON COLUMN "public"."regras_logisticas_canal"."modalidade" IS 'Modalidade logística vinculada (STANDARD, EXPRESS, FULFILLMENT, RETIRADA)';



COMMENT ON COLUMN "public"."regras_logisticas_canal"."tipo_envio" IS 'Tipo da janela (COLETA_LOCAL para quando buscam na empresa, PONTO_COLETA para quando levamos)';



CREATE SEQUENCE IF NOT EXISTS "public"."regras_logisticas_canal_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."regras_logisticas_canal_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."regras_logisticas_canal_id_seq" OWNED BY "public"."regras_logisticas_canal"."id";



CREATE TABLE IF NOT EXISTS "public"."setores" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" "text",
    "ativo" boolean DEFAULT true NOT NULL,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."setores" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."setores_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."setores_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."setores_id_seq" OWNED BY "public"."setores"."id";



CREATE TABLE IF NOT EXISTS "public"."situacoes_pedido" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" "text",
    "flag_reserva_estoque" boolean DEFAULT false,
    "flag_fatura" boolean DEFAULT false,
    "flag_cancelado" boolean DEFAULT false,
    "cor_status" character varying(7) DEFAULT '#007bff'::character varying,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."situacoes_pedido" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."situacoes_pedido_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."situacoes_pedido_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."situacoes_pedido_id_seq" OWNED BY "public"."situacoes_pedido"."id";



CREATE TABLE IF NOT EXISTS "public"."system_events_log" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "severity" "text" DEFAULT 'ERROR'::"text" NOT NULL,
    "category" "text" NOT NULL,
    "action" "text",
    "message" "text" NOT NULL,
    "reference_id" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb",
    "resolved" boolean DEFAULT false,
    "user_id" "text"
);


ALTER TABLE "public"."system_events_log" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."tags" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "descricao" "text",
    "cor" character varying(7),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."tags" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."tags_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."tags_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."tags_id_seq" OWNED BY "public"."tags"."id";



CREATE TABLE IF NOT EXISTS "public"."transicoes_situacao" (
    "id" integer NOT NULL,
    "situacao_origem_id" integer NOT NULL,
    "situacao_destino_id" integer NOT NULL,
    "regra_permissao" character varying(100),
    "descricao_transicao" "text",
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."transicoes_situacao" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."transicoes_situacao_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."transicoes_situacao_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."transicoes_situacao_id_seq" OWNED BY "public"."transicoes_situacao"."id";



CREATE TABLE IF NOT EXISTS "public"."unidades_medida" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "abreviacao" character varying(20),
    "descricao" "text",
    "tipo" character varying(50),
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."unidades_medida" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."unidades_medida_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."unidades_medida_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."unidades_medida_id_seq" OWNED BY "public"."unidades_medida"."id";



CREATE TABLE IF NOT EXISTS "public"."usuarios" (
    "id" integer NOT NULL,
    "nome" character varying(100) NOT NULL,
    "email" character varying(120) NOT NULL,
    "senha_hash" character varying(256),
    "setor_id" integer NOT NULL,
    "ativo" boolean DEFAULT true NOT NULL,
    "is_admin" boolean DEFAULT false NOT NULL,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "last_login" timestamp without time zone
);


ALTER TABLE "public"."usuarios" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."usuarios_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."usuarios_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."usuarios_id_seq" OWNED BY "public"."usuarios"."id";



CREATE TABLE IF NOT EXISTS "public"."vendas" (
    "id" integer NOT NULL,
    "venda_id" character varying(255) NOT NULL,
    "plataforma" character varying(100),
    "status" character varying(50),
    "valor_total" numeric(10,2),
    "moeda" character varying(10),
    "informacoes_cliente" "jsonb",
    "endereco_entrega" "jsonb",
    "itens" "jsonb",
    "data_venda" timestamp without time zone,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "total_amount" numeric(10,2),
    "currency" character varying(10),
    "cliente_info" "jsonb"
);


ALTER TABLE "public"."vendas" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."vendas_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."vendas_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."vendas_id_seq" OWNED BY "public"."vendas"."id";



CREATE OR REPLACE VIEW "public"."view_consolidado_producao" AS
 SELECT "i"."id" AS "item_id",
    "i"."demanda_id",
    "d"."descricao" AS "demanda_nome",
    "d"."data_entrega",
    "d"."horario_coleta",
    "i"."sku",
    "i"."descricao" AS "item_nome",
    "i"."quantidade" AS "qtd_total",
    "i"."capas_impressas_qtd",
    "i"."capas_produzidas_qtd" AS "capas_prontas",
    "i"."miolos_prontos_retirada_qtd" AS "miolos_prontos",
    LEAST("i"."capas_produzidas_qtd", "i"."miolos_prontos_retirada_qtd") AS "match_disponivel",
    "d"."status" AS "demanda_status",
    "i"."status_item",
        CASE
            WHEN ("d"."prioridade_manual" >= 100) THEN 'URGENTE'::"text"
            WHEN "d"."is_flex" THEN 'FLEX'::"text"
            ELSE 'NORMAL'::"text"
        END AS "trilha",
    "d"."updated_at" AS "status_sincronia"
   FROM ("public"."itens_demanda" "i"
     JOIN "public"."demandas_producao" "d" ON (("i"."demanda_id" = "d"."id")))
  WHERE (("d"."status")::"text" <> ALL ((ARRAY['Finalizado'::character varying, 'Coletado'::character varying, 'Cancelado'::character varying])::"text"[]));


ALTER VIEW "public"."view_consolidado_producao" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."view_mensagens_chat" AS
 WITH "processed_msgs" AS (
         SELECT "mensagem_chat_shopee"."id",
            "mensagem_chat_shopee"."from_user_name",
            "mensagem_chat_shopee"."to_user_name",
            "mensagem_chat_shopee"."created_at",
            "mensagem_chat_shopee"."type",
                CASE
                    WHEN ("jsonb_typeof"("mensagem_chat_shopee"."content") = 'string'::"text") THEN (("mensagem_chat_shopee"."content" #>> '{}'::"text"[]))::"jsonb"
                    ELSE "mensagem_chat_shopee"."content"
                END AS "content_json"
           FROM "public"."mensagem_chat_shopee"
        )
 SELECT "id",
    "from_user_name",
    "to_user_name",
    "content_json" AS "content",
    "created_at",
    "type",
        CASE
            WHEN ("type" = 'text'::"text") THEN ("content_json" ->> 'text'::"text")
            WHEN ("type" = 'new_faq'::"text") THEN ("content_json" ->> 'opening'::"text")
            WHEN ("type" = 'notification'::"text") THEN ("content_json" ->> 'notification_for_sender'::"text")
            WHEN (("content_json" ->> 'sticker_id'::"text") IS NOT NULL) THEN '[figurinha]'::"text"
            ELSE COALESCE(("content_json" ->> 'text'::"text"), 'Mensagem sem conteúdo'::"text")
        END AS "display_content"
   FROM "processed_msgs"
  WHERE ("type" <> ALL (ARRAY['faq_unsupported'::"text", 'faq_question_list'::"text", 'faq_category_choice'::"text", 'faq_feedback_prompt'::"text"]));


ALTER VIEW "public"."view_mensagens_chat" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."view_vendas_personalizadas" AS
 SELECT "pb"."id",
    "pb"."numero_pedido",
    "pb"."numero_loja",
    "pb"."data_pedido",
    "pb"."contato",
    "pb"."bling_id",
    "pb"."personalizado",
    "pb"."deletado",
    "ps"."informacoes_comprador",
    "ps"."mensagem" AS "shopee_message",
    COALESCE(("ps"."informacoes_comprador" ->> 'username'::"text"), ((("ps"."informacoes_comprador" #>> '{}'::"text"[]))::"jsonb" ->> 'username'::"text")) AS "buyer_username",
    (EXISTS ( SELECT 1
           FROM "public"."mensagem_chat_shopee" "mcs"
          WHERE (("mcs"."from_user_name" = COALESCE(("ps"."informacoes_comprador" ->> 'username'::"text"), ((("ps"."informacoes_comprador" #>> '{}'::"text"[]))::"jsonb" ->> 'username'::"text"))) OR ("mcs"."to_user_name" = COALESCE(("ps"."informacoes_comprador" ->> 'username'::"text"), ((("ps"."informacoes_comprador" #>> '{}'::"text"[]))::"jsonb" ->> 'username'::"text")))))) AS "has_chat_messages",
    "agg_itens"."itens_json" AS "itens"
   FROM (("public"."pedidos_bling" "pb"
     LEFT JOIN "public"."pedidos_shopee" "ps" ON (("pb"."numero_loja" = ("ps"."codigo_pedido")::"text")))
     LEFT JOIN LATERAL ( SELECT "jsonb_agg"("item_flat".*) AS "itens_json"
           FROM ( SELECT "it"."id",
                    "it"."codigo",
                    "it"."unidade",
                    "it"."quantidade",
                    "it"."valor",
                    "it"."descricao",
                    "it"."personalizado",
                    "it"."produto",
                    "agg_pers"."pers_json" AS "personalizations"
                   FROM ("public"."itens_pedido_bling" "it"
                     LEFT JOIN LATERAL ( SELECT "jsonb_agg"("p_json".*) AS "pers_json"
                           FROM ( SELECT "p"."id" AS "personalization_id",
                                    "p"."item_id",
                                    "p"."item_description",
                                    "p"."customization_name",
                                    "p"."customization_initial",
                                    "p"."name_source_message_id",
                                    "p"."status",
                                    "p"."reasoning"
                                   FROM "public"."personalizacoes_pedido" "p"
                                  WHERE (("p"."shopee_order_sn" = "pb"."numero_loja") AND ("p"."item_description" = ("it"."descricao")::"text"))) "p_json") "agg_pers" ON (true))
                  WHERE ("it"."pedido_bling_id" = "pb"."id")) "item_flat") "agg_itens" ON (true))
  WHERE ("pb"."personalizado" IS TRUE);


ALTER VIEW "public"."view_vendas_personalizadas" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."vinculos_integracao_pedido" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "pedido_id" integer NOT NULL,
    "plataforma" character varying(50) NOT NULL,
    "id_na_plataforma" character varying(100) NOT NULL,
    "status_na_plataforma" character varying(50),
    "dados_brutos" "jsonb",
    "last_synced_at" timestamp with time zone DEFAULT "now"(),
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."vinculos_integracao_pedido" OWNER TO "postgres";


CREATE OR REPLACE VIEW "public"."view_vendas_personalizadas_v3" AS
 SELECT "p"."id",
    "p"."numero_pedido",
    "p"."codigo_pedido_externo" AS "numero_loja",
    "p"."data_venda" AS "data_pedido",
    "p"."informacoes_cliente" AS "contato",
    "v_bling"."id_na_plataforma" AS "bling_id",
    true AS "personalizado",
    false AS "deletado",
    COALESCE(("v_shopee"."dados_brutos" -> 'informacoes_comprador'::"text"), "p"."informacoes_cliente") AS "informacoes_comprador",
    ("v_shopee"."dados_brutos" ->> 'mensagem'::"text") AS "shopee_message",
    COALESCE((("v_shopee"."dados_brutos" -> 'informacoes_comprador'::"text") ->> 'username'::"text"), ("p"."cliente_nome")::"text") AS "buyer_username",
    (EXISTS ( SELECT 1
           FROM "public"."mensagem_chat_shopee" "mcs"
          WHERE (("mcs"."from_user_name" = COALESCE((("v_shopee"."dados_brutos" -> 'informacoes_comprador'::"text") ->> 'username'::"text"), ("p"."cliente_nome")::"text")) OR ("mcs"."to_user_name" = COALESCE((("v_shopee"."dados_brutos" -> 'informacoes_comprador'::"text") ->> 'username'::"text"), ("p"."cliente_nome")::"text"))))) AS "has_chat_messages",
    COALESCE(( SELECT "jsonb_agg"("jsonb_build_object"('id', "ip"."id", 'codigo', "ip"."sku_externo", 'descricao', "ip"."descricao", 'quantidade', "ip"."quantidade", 'valor', "ip"."preco_unitario", 'unidade', 'UN', 'personalizado', true, 'produto', "jsonb_build_object"('id', "ip"."produto_id"))) AS "jsonb_agg"
           FROM "public"."itens_pedido" "ip"
          WHERE ("ip"."pedido_id" = "p"."id")), '[]'::"jsonb") AS "itens"
   FROM (("public"."pedidos" "p"
     LEFT JOIN "public"."vinculos_integracao_pedido" "v_bling" ON ((("p"."id" = "v_bling"."pedido_id") AND (("v_bling"."plataforma")::"text" = 'BLING'::"text"))))
     LEFT JOIN "public"."vinculos_integracao_pedido" "v_shopee" ON ((("p"."id" = "v_shopee"."pedido_id") AND (("v_shopee"."plataforma")::"text" = 'SHOPEE'::"text"))))
  WHERE (("p"."origem")::"text" = ANY ((ARRAY['SHOPEE'::character varying, 'BLING'::character varying])::"text"[]));


ALTER VIEW "public"."view_vendas_personalizadas_v3" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."vinculos_bling" (
    "id" integer NOT NULL,
    "produto_id" integer NOT NULL,
    "codigo_bling" character varying(255) NOT NULL,
    "configuracao_sync" "jsonb",
    "ultimo_sync" timestamp without time zone,
    "status_sync" character varying(50) DEFAULT 'PENDENTE'::character varying,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "public"."vinculos_bling" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."vinculos_bling_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."vinculos_bling_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."vinculos_bling_id_seq" OWNED BY "public"."vinculos_bling"."id";



CREATE TABLE IF NOT EXISTS "public"."webhook_logs" (
    "id" integer NOT NULL,
    "plataforma" character varying(50) NOT NULL,
    "instance_id" character varying(255),
    "evento" character varying(100),
    "payload" "jsonb" NOT NULL,
    "headers" "jsonb",
    "status" character varying(20) DEFAULT 'PENDENTE'::character varying,
    "mensagem_erro" "text",
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "processed_at" timestamp with time zone
);


ALTER TABLE "public"."webhook_logs" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."webhook_logs_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."webhook_logs_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."webhook_logs_id_seq" OWNED BY "public"."webhook_logs"."id";



CREATE TABLE IF NOT EXISTS "storage"."buckets" (
    "id" "text" NOT NULL,
    "name" "text" NOT NULL,
    "owner" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "public" boolean DEFAULT false,
    "avif_autodetection" boolean DEFAULT false,
    "file_size_limit" bigint,
    "allowed_mime_types" "text"[],
    "owner_id" "text",
    "type" "storage"."buckettype" DEFAULT 'STANDARD'::"storage"."buckettype" NOT NULL
);


ALTER TABLE "storage"."buckets" OWNER TO "supabase_storage_admin";


COMMENT ON COLUMN "storage"."buckets"."owner" IS 'Field is deprecated, use owner_id instead';



CREATE TABLE IF NOT EXISTS "storage"."buckets_analytics" (
    "name" "text" NOT NULL,
    "type" "storage"."buckettype" DEFAULT 'ANALYTICS'::"storage"."buckettype" NOT NULL,
    "format" "text" DEFAULT 'ICEBERG'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "deleted_at" timestamp with time zone
);


ALTER TABLE "storage"."buckets_analytics" OWNER TO "supabase_storage_admin";


CREATE TABLE IF NOT EXISTS "storage"."buckets_vectors" (
    "id" "text" NOT NULL,
    "type" "storage"."buckettype" DEFAULT 'VECTOR'::"storage"."buckettype" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "storage"."buckets_vectors" OWNER TO "supabase_storage_admin";


CREATE TABLE IF NOT EXISTS "storage"."migrations" (
    "id" integer NOT NULL,
    "name" character varying(100) NOT NULL,
    "hash" character varying(40) NOT NULL,
    "executed_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE "storage"."migrations" OWNER TO "supabase_storage_admin";


CREATE TABLE IF NOT EXISTS "storage"."objects" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "bucket_id" "text",
    "name" "text",
    "owner" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "last_accessed_at" timestamp with time zone DEFAULT "now"(),
    "metadata" "jsonb",
    "path_tokens" "text"[] GENERATED ALWAYS AS ("string_to_array"("name", '/'::"text")) STORED,
    "version" "text",
    "owner_id" "text",
    "user_metadata" "jsonb"
);


ALTER TABLE "storage"."objects" OWNER TO "supabase_storage_admin";


COMMENT ON COLUMN "storage"."objects"."owner" IS 'Field is deprecated, use owner_id instead';



CREATE TABLE IF NOT EXISTS "storage"."s3_multipart_uploads" (
    "id" "text" NOT NULL,
    "in_progress_size" bigint DEFAULT 0 NOT NULL,
    "upload_signature" "text" NOT NULL,
    "bucket_id" "text" NOT NULL,
    "key" "text" NOT NULL COLLATE "pg_catalog"."C",
    "version" "text" NOT NULL,
    "owner_id" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_metadata" "jsonb"
);


ALTER TABLE "storage"."s3_multipart_uploads" OWNER TO "supabase_storage_admin";


CREATE TABLE IF NOT EXISTS "storage"."s3_multipart_uploads_parts" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "upload_id" "text" NOT NULL,
    "size" bigint DEFAULT 0 NOT NULL,
    "part_number" integer NOT NULL,
    "bucket_id" "text" NOT NULL,
    "key" "text" NOT NULL COLLATE "pg_catalog"."C",
    "etag" "text" NOT NULL,
    "owner_id" "text",
    "version" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "storage"."s3_multipart_uploads_parts" OWNER TO "supabase_storage_admin";


CREATE TABLE IF NOT EXISTS "storage"."vector_indexes" (
    "id" "text" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL COLLATE "pg_catalog"."C",
    "bucket_id" "text" NOT NULL,
    "data_type" "text" NOT NULL,
    "dimension" integer NOT NULL,
    "distance_metric" "text" NOT NULL,
    "metadata_configuration" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "storage"."vector_indexes" OWNER TO "supabase_storage_admin";


ALTER TABLE ONLY "auth"."refresh_tokens" ALTER COLUMN "id" SET DEFAULT "nextval"('"auth"."refresh_tokens_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."agenda_recursos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."agenda_recursos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."canais_venda" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."canais_venda_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."categoria_bom_regras" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."categoria_bom_regras_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."categorias" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."categorias_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."componentes_ordem_producao" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."componentes_ordem_producao_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."configuracoes_aplicacao" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."configuracoes_aplicacao_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."conversoes_uom_produto" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."conversoes_uom_produto_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."demandas_item_origem" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."demandas_item_origem_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."demandas_producao" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."demandas_producao_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."depositos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."depositos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."estoque_atual" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."estoque_atual_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."eventos_auditoria" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."eventos_auditoria_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."feedback_pedido" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."feedback_pedido_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."ficha_tecnica" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."ficha_tecnica_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."fornecedor_insumos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."fornecedor_insumos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."fornecedores" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."fornecedores_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."identificadores_alternativos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."identificadores_alternativos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."installed_integrations" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."installed_integrations_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."integration_refresh_logs" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."integration_refresh_logs_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."itens_demanda" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."itens_demanda_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."itens_ordem_compra" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."itens_ordem_compra_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."itens_pedido" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."itens_pedido_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."itens_pedido_bling" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."itens_pedido_bling_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."itens_venda" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."itens_venda_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."logs_producao_diaria" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."logs_producao_diaria_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."movimentacoes_estoque" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."movimentacoes_estoque_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."notificacoes" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."notificacoes_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."ordens_compra" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."ordens_compra_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."ordens_producao" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."ordens_producao_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pedidos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pedidos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pedidos_bling" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pedidos_bling_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pedidos_shopee" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pedidos_shopee_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."permissoes_setor" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."permissoes_setor_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."personalizacoes_pedido" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."personalizacoes_pedido_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."plataformas" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."plataformas_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."pontos_coleta" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."pontos_coleta_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."print_jobs" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."print_jobs_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."product_artworks" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."product_artworks_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."produtos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."produtos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."produtos_externos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."produtos_externos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."recursos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."recursos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."recursos_produtivos" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."recursos_produtivos_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."regras_logisticas_canal" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."regras_logisticas_canal_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."setores" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."setores_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."situacoes_pedido" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."situacoes_pedido_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."tags" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."tags_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."transicoes_situacao" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."transicoes_situacao_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."unidades_medida" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."unidades_medida_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."usuarios" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."usuarios_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."vendas" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."vendas_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."vinculos_bling" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."vinculos_bling_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."webhook_logs" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."webhook_logs_id_seq"'::"regclass");



ALTER TABLE ONLY "auth"."mfa_amr_claims"
    ADD CONSTRAINT "amr_id_pk" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."audit_log_entries"
    ADD CONSTRAINT "audit_log_entries_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."custom_oauth_providers"
    ADD CONSTRAINT "custom_oauth_providers_identifier_key" UNIQUE ("identifier");



ALTER TABLE ONLY "auth"."custom_oauth_providers"
    ADD CONSTRAINT "custom_oauth_providers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."flow_state"
    ADD CONSTRAINT "flow_state_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."identities"
    ADD CONSTRAINT "identities_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."identities"
    ADD CONSTRAINT "identities_provider_id_provider_unique" UNIQUE ("provider_id", "provider");



ALTER TABLE ONLY "auth"."instances"
    ADD CONSTRAINT "instances_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."mfa_amr_claims"
    ADD CONSTRAINT "mfa_amr_claims_session_id_authentication_method_pkey" UNIQUE ("session_id", "authentication_method");



ALTER TABLE ONLY "auth"."mfa_challenges"
    ADD CONSTRAINT "mfa_challenges_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."mfa_factors"
    ADD CONSTRAINT "mfa_factors_last_challenged_at_key" UNIQUE ("last_challenged_at");



ALTER TABLE ONLY "auth"."mfa_factors"
    ADD CONSTRAINT "mfa_factors_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."oauth_authorizations"
    ADD CONSTRAINT "oauth_authorizations_authorization_code_key" UNIQUE ("authorization_code");



ALTER TABLE ONLY "auth"."oauth_authorizations"
    ADD CONSTRAINT "oauth_authorizations_authorization_id_key" UNIQUE ("authorization_id");



ALTER TABLE ONLY "auth"."oauth_authorizations"
    ADD CONSTRAINT "oauth_authorizations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."oauth_client_states"
    ADD CONSTRAINT "oauth_client_states_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."oauth_clients"
    ADD CONSTRAINT "oauth_clients_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."oauth_consents"
    ADD CONSTRAINT "oauth_consents_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."oauth_consents"
    ADD CONSTRAINT "oauth_consents_user_client_unique" UNIQUE ("user_id", "client_id");



ALTER TABLE ONLY "auth"."one_time_tokens"
    ADD CONSTRAINT "one_time_tokens_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."refresh_tokens"
    ADD CONSTRAINT "refresh_tokens_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."refresh_tokens"
    ADD CONSTRAINT "refresh_tokens_token_unique" UNIQUE ("token");



ALTER TABLE ONLY "auth"."saml_providers"
    ADD CONSTRAINT "saml_providers_entity_id_key" UNIQUE ("entity_id");



ALTER TABLE ONLY "auth"."saml_providers"
    ADD CONSTRAINT "saml_providers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."saml_relay_states"
    ADD CONSTRAINT "saml_relay_states_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."schema_migrations"
    ADD CONSTRAINT "schema_migrations_pkey" PRIMARY KEY ("version");



ALTER TABLE ONLY "auth"."sessions"
    ADD CONSTRAINT "sessions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."sso_domains"
    ADD CONSTRAINT "sso_domains_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."sso_providers"
    ADD CONSTRAINT "sso_providers_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "auth"."users"
    ADD CONSTRAINT "users_phone_key" UNIQUE ("phone");



ALTER TABLE ONLY "auth"."users"
    ADD CONSTRAINT "users_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."agenda_recursos"
    ADD CONSTRAINT "agenda_recursos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."logs_execucao_ia"
    ADD CONSTRAINT "ai_execution_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."cache_dashboard_pedidos"
    ADD CONSTRAINT "cache_dashboard_orders_pkey" PRIMARY KEY ("order_sn");



ALTER TABLE ONLY "public"."canais_venda"
    ADD CONSTRAINT "canais_venda_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."canais_venda"
    ADD CONSTRAINT "canais_venda_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."categoria_bom_regras"
    ADD CONSTRAINT "categoria_bom_regras_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."categorias"
    ADD CONSTRAINT "categorias_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."categorias"
    ADD CONSTRAINT "categorias_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."componentes_ordem_producao"
    ADD CONSTRAINT "componentes_ordem_producao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."configuracoes_aplicacao"
    ADD CONSTRAINT "configuracoes_aplicacao_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."configuracoes_aplicacao"
    ADD CONSTRAINT "configuracoes_aplicacao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."contas_bling"
    ADD CONSTRAINT "contas_bling_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."conversoes_uom_produto"
    ADD CONSTRAINT "conversoes_uom_produto_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."demandas_item_origem"
    ADD CONSTRAINT "demandas_item_origem_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_demanda_id_key" UNIQUE ("demanda_id");



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."depositos"
    ADD CONSTRAINT "depositos_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."depositos"
    ADD CONSTRAINT "depositos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."entrega_producao"
    ADD CONSTRAINT "entrega_producao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."estoque_atual"
    ADD CONSTRAINT "estoque_atual_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."estoque_atual"
    ADD CONSTRAINT "estoque_atual_produto_id_deposito_id_key" UNIQUE ("produto_id", "deposito_id");



ALTER TABLE ONLY "public"."eventos_auditoria"
    ADD CONSTRAINT "eventos_auditoria_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."feedback_pedido"
    ADD CONSTRAINT "feedback_pedido_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ficha_tecnica"
    ADD CONSTRAINT "ficha_tecnica_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ficha_tecnica"
    ADD CONSTRAINT "ficha_tecnica_produto_pai_id_componente_id_key" UNIQUE ("produto_pai_id", "componente_id");



ALTER TABLE ONLY "public"."fornecedor_insumos"
    ADD CONSTRAINT "fornecedor_insumos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."fornecedores"
    ADD CONSTRAINT "fornecedores_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."identificadores_alternativos"
    ADD CONSTRAINT "identificadores_alternativos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."installed_integrations"
    ADD CONSTRAINT "installed_integrations_module_instance_key" UNIQUE ("module_id", "instance_name");



ALTER TABLE ONLY "public"."installed_integrations"
    ADD CONSTRAINT "installed_integrations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."integration_modules"
    ADD CONSTRAINT "integration_modules_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."integration_refresh_logs"
    ADD CONSTRAINT "integration_refresh_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."itens_demanda"
    ADD CONSTRAINT "itens_demanda_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."itens_ordem_compra"
    ADD CONSTRAINT "itens_ordem_compra_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."itens_pedido_bling"
    ADD CONSTRAINT "itens_pedido_bling_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."itens_pedido"
    ADD CONSTRAINT "itens_pedido_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."itens_venda"
    ADD CONSTRAINT "itens_venda_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."logs_producao_diaria"
    ADD CONSTRAINT "logs_producao_diaria_data_turno_equipe_id_key" UNIQUE ("data", "turno", "equipe_id");



ALTER TABLE ONLY "public"."logs_producao_diaria"
    ADD CONSTRAINT "logs_producao_diaria_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."movimentacoes_estoque"
    ADD CONSTRAINT "movimentacoes_estoque_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."feedbacks_negativo"
    ADD CONSTRAINT "negative_feedback_snapshots_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."notificacoes"
    ADD CONSTRAINT "notificacoes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ordens_compra"
    ADD CONSTRAINT "ordens_compra_numero_ordem_key" UNIQUE ("numero_ordem");



ALTER TABLE ONLY "public"."ordens_compra"
    ADD CONSTRAINT "ordens_compra_ordem_compra_id_key" UNIQUE ("ordem_compra_id");



ALTER TABLE ONLY "public"."ordens_compra"
    ADD CONSTRAINT "ordens_compra_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."ordens_producao"
    ADD CONSTRAINT "ordens_producao_numero_ordem_key" UNIQUE ("numero_ordem");



ALTER TABLE ONLY "public"."ordens_producao"
    ADD CONSTRAINT "ordens_producao_ordem_id_key" UNIQUE ("ordem_id");



ALTER TABLE ONLY "public"."ordens_producao"
    ADD CONSTRAINT "ordens_producao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."feedbacks_execucao_ia"
    ADD CONSTRAINT "order_feedback_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pedidos_bling"
    ADD CONSTRAINT "pedidos_bling_numero_pedido_key" UNIQUE ("numero_pedido");



ALTER TABLE ONLY "public"."pedidos_bling"
    ADD CONSTRAINT "pedidos_bling_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_codigo_pedido_externo_key" UNIQUE ("codigo_pedido_externo");



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_numero_pedido_key" UNIQUE ("numero_pedido");



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pedidos_shopee"
    ADD CONSTRAINT "pedidos_shopee_codigo_pedido_key" UNIQUE ("codigo_pedido");



ALTER TABLE ONLY "public"."pedidos_shopee"
    ADD CONSTRAINT "pedidos_shopee_id_pedido_shopee_key" UNIQUE ("id_pedido_shopee");



ALTER TABLE ONLY "public"."pedidos_shopee"
    ADD CONSTRAINT "pedidos_shopee_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_uuid_pedido_key" UNIQUE ("uuid_pedido");



ALTER TABLE ONLY "public"."permissoes_setor"
    ADD CONSTRAINT "permissoes_setor_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."personalizacoes_pedido"
    ADD CONSTRAINT "personalizacoes_pedido_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."plataformas"
    ADD CONSTRAINT "plataformas_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."plataformas"
    ADD CONSTRAINT "plataformas_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."pontos_coleta"
    ADD CONSTRAINT "pontos_coleta_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."print_jobs"
    ADD CONSTRAINT "print_jobs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."product_artworks"
    ADD CONSTRAINT "product_artworks_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."produtos_externos"
    ADD CONSTRAINT "produtos_externos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."produtos"
    ADD CONSTRAINT "produtos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."produtos"
    ADD CONSTRAINT "produtos_sku_key" UNIQUE ("sku");



ALTER TABLE ONLY "public"."recursos"
    ADD CONSTRAINT "recursos_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."recursos"
    ADD CONSTRAINT "recursos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."recursos_produtivos"
    ADD CONSTRAINT "recursos_produtivos_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."recursos_produtivos"
    ADD CONSTRAINT "recursos_produtivos_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."regras_logisticas_canal"
    ADD CONSTRAINT "regras_logisticas_canal_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."setores"
    ADD CONSTRAINT "setores_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."setores"
    ADD CONSTRAINT "setores_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."situacoes_pedido"
    ADD CONSTRAINT "situacoes_pedido_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."situacoes_pedido"
    ADD CONSTRAINT "situacoes_pedido_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."system_events_log"
    ADD CONSTRAINT "system_events_log_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tags"
    ADD CONSTRAINT "tags_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."tags"
    ADD CONSTRAINT "tags_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."transicoes_situacao"
    ADD CONSTRAINT "transicoes_situacao_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."transicoes_situacao"
    ADD CONSTRAINT "transicoes_situacao_situacao_origem_id_situacao_destino_id_key" UNIQUE ("situacao_origem_id", "situacao_destino_id");



ALTER TABLE ONLY "public"."identificadores_alternativos"
    ADD CONSTRAINT "uk_tipo_valor" UNIQUE ("tipo_identificador", "valor_identificador");



ALTER TABLE ONLY "public"."unidades_medida"
    ADD CONSTRAINT "unidades_medida_nome_key" UNIQUE ("nome");



ALTER TABLE ONLY "public"."unidades_medida"
    ADD CONSTRAINT "unidades_medida_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."configuracoes_aplicacao"
    ADD CONSTRAINT "unique_config_per_entity" UNIQUE ("nome", "entidade_tipo", "entidade_id");



ALTER TABLE ONLY "public"."pedidos_bling"
    ADD CONSTRAINT "unique_numero_pedido" UNIQUE ("numero_pedido");



ALTER TABLE ONLY "public"."produtos_externos"
    ADD CONSTRAINT "unique_plataforma_codigo_externo" UNIQUE ("plataforma", "codigo_externo");



ALTER TABLE ONLY "public"."usuarios"
    ADD CONSTRAINT "usuarios_email_key" UNIQUE ("email");



ALTER TABLE ONLY "public"."usuarios"
    ADD CONSTRAINT "usuarios_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."grupo_mensagens_chat_shopee"
    ADD CONSTRAINT "v2_bundle_messages_pkey" PRIMARY KEY ("event_id", "msg_id");



ALTER TABLE ONLY "public"."mensagem_chat_shopee"
    ADD CONSTRAINT "v2_chat_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."vendas"
    ADD CONSTRAINT "vendas_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."vendas"
    ADD CONSTRAINT "vendas_venda_id_key" UNIQUE ("venda_id");



ALTER TABLE ONLY "public"."vinculos_bling"
    ADD CONSTRAINT "vinculos_bling_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."vinculos_bling"
    ADD CONSTRAINT "vinculos_bling_produto_id_codigo_bling_key" UNIQUE ("produto_id", "codigo_bling");



ALTER TABLE ONLY "public"."vinculos_integracao_pedido"
    ADD CONSTRAINT "vinculos_integracao_pedido_pedido_id_plataforma_key" UNIQUE ("pedido_id", "plataforma");



ALTER TABLE ONLY "public"."vinculos_integracao_pedido"
    ADD CONSTRAINT "vinculos_integracao_pedido_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."webhook_logs"
    ADD CONSTRAINT "webhook_logs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "storage"."buckets_analytics"
    ADD CONSTRAINT "buckets_analytics_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "storage"."buckets"
    ADD CONSTRAINT "buckets_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "storage"."buckets_vectors"
    ADD CONSTRAINT "buckets_vectors_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "storage"."migrations"
    ADD CONSTRAINT "migrations_name_key" UNIQUE ("name");



ALTER TABLE ONLY "storage"."migrations"
    ADD CONSTRAINT "migrations_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "storage"."objects"
    ADD CONSTRAINT "objects_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "storage"."s3_multipart_uploads_parts"
    ADD CONSTRAINT "s3_multipart_uploads_parts_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "storage"."s3_multipart_uploads"
    ADD CONSTRAINT "s3_multipart_uploads_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "storage"."vector_indexes"
    ADD CONSTRAINT "vector_indexes_pkey" PRIMARY KEY ("id");



CREATE INDEX "audit_logs_instance_id_idx" ON "auth"."audit_log_entries" USING "btree" ("instance_id");



CREATE UNIQUE INDEX "confirmation_token_idx" ON "auth"."users" USING "btree" ("confirmation_token") WHERE (("confirmation_token")::"text" !~ '^[0-9 ]*$'::"text");



CREATE INDEX "custom_oauth_providers_created_at_idx" ON "auth"."custom_oauth_providers" USING "btree" ("created_at");



CREATE INDEX "custom_oauth_providers_enabled_idx" ON "auth"."custom_oauth_providers" USING "btree" ("enabled");



CREATE INDEX "custom_oauth_providers_identifier_idx" ON "auth"."custom_oauth_providers" USING "btree" ("identifier");



CREATE INDEX "custom_oauth_providers_provider_type_idx" ON "auth"."custom_oauth_providers" USING "btree" ("provider_type");



CREATE UNIQUE INDEX "email_change_token_current_idx" ON "auth"."users" USING "btree" ("email_change_token_current") WHERE (("email_change_token_current")::"text" !~ '^[0-9 ]*$'::"text");



CREATE UNIQUE INDEX "email_change_token_new_idx" ON "auth"."users" USING "btree" ("email_change_token_new") WHERE (("email_change_token_new")::"text" !~ '^[0-9 ]*$'::"text");



CREATE INDEX "factor_id_created_at_idx" ON "auth"."mfa_factors" USING "btree" ("user_id", "created_at");



CREATE INDEX "flow_state_created_at_idx" ON "auth"."flow_state" USING "btree" ("created_at" DESC);



CREATE INDEX "identities_email_idx" ON "auth"."identities" USING "btree" ("email" "text_pattern_ops");



COMMENT ON INDEX "auth"."identities_email_idx" IS 'Auth: Ensures indexed queries on the email column';



CREATE INDEX "identities_user_id_idx" ON "auth"."identities" USING "btree" ("user_id");



CREATE INDEX "idx_auth_code" ON "auth"."flow_state" USING "btree" ("auth_code");



CREATE INDEX "idx_oauth_client_states_created_at" ON "auth"."oauth_client_states" USING "btree" ("created_at");



CREATE INDEX "idx_user_id_auth_method" ON "auth"."flow_state" USING "btree" ("user_id", "authentication_method");



CREATE INDEX "mfa_challenge_created_at_idx" ON "auth"."mfa_challenges" USING "btree" ("created_at" DESC);



CREATE UNIQUE INDEX "mfa_factors_user_friendly_name_unique" ON "auth"."mfa_factors" USING "btree" ("friendly_name", "user_id") WHERE (TRIM(BOTH FROM "friendly_name") <> ''::"text");



CREATE INDEX "mfa_factors_user_id_idx" ON "auth"."mfa_factors" USING "btree" ("user_id");



CREATE INDEX "oauth_auth_pending_exp_idx" ON "auth"."oauth_authorizations" USING "btree" ("expires_at") WHERE ("status" = 'pending'::"auth"."oauth_authorization_status");



CREATE INDEX "oauth_clients_deleted_at_idx" ON "auth"."oauth_clients" USING "btree" ("deleted_at");



CREATE INDEX "oauth_consents_active_client_idx" ON "auth"."oauth_consents" USING "btree" ("client_id") WHERE ("revoked_at" IS NULL);



CREATE INDEX "oauth_consents_active_user_client_idx" ON "auth"."oauth_consents" USING "btree" ("user_id", "client_id") WHERE ("revoked_at" IS NULL);



CREATE INDEX "oauth_consents_user_order_idx" ON "auth"."oauth_consents" USING "btree" ("user_id", "granted_at" DESC);



CREATE INDEX "one_time_tokens_relates_to_hash_idx" ON "auth"."one_time_tokens" USING "hash" ("relates_to");



CREATE INDEX "one_time_tokens_token_hash_hash_idx" ON "auth"."one_time_tokens" USING "hash" ("token_hash");



CREATE UNIQUE INDEX "one_time_tokens_user_id_token_type_key" ON "auth"."one_time_tokens" USING "btree" ("user_id", "token_type");



CREATE UNIQUE INDEX "reauthentication_token_idx" ON "auth"."users" USING "btree" ("reauthentication_token") WHERE (("reauthentication_token")::"text" !~ '^[0-9 ]*$'::"text");



CREATE UNIQUE INDEX "recovery_token_idx" ON "auth"."users" USING "btree" ("recovery_token") WHERE (("recovery_token")::"text" !~ '^[0-9 ]*$'::"text");



CREATE INDEX "refresh_tokens_instance_id_idx" ON "auth"."refresh_tokens" USING "btree" ("instance_id");



CREATE INDEX "refresh_tokens_instance_id_user_id_idx" ON "auth"."refresh_tokens" USING "btree" ("instance_id", "user_id");



CREATE INDEX "refresh_tokens_parent_idx" ON "auth"."refresh_tokens" USING "btree" ("parent");



CREATE INDEX "refresh_tokens_session_id_revoked_idx" ON "auth"."refresh_tokens" USING "btree" ("session_id", "revoked");



CREATE INDEX "refresh_tokens_updated_at_idx" ON "auth"."refresh_tokens" USING "btree" ("updated_at" DESC);



CREATE INDEX "saml_providers_sso_provider_id_idx" ON "auth"."saml_providers" USING "btree" ("sso_provider_id");



CREATE INDEX "saml_relay_states_created_at_idx" ON "auth"."saml_relay_states" USING "btree" ("created_at" DESC);



CREATE INDEX "saml_relay_states_for_email_idx" ON "auth"."saml_relay_states" USING "btree" ("for_email");



CREATE INDEX "saml_relay_states_sso_provider_id_idx" ON "auth"."saml_relay_states" USING "btree" ("sso_provider_id");



CREATE INDEX "sessions_not_after_idx" ON "auth"."sessions" USING "btree" ("not_after" DESC);



CREATE INDEX "sessions_oauth_client_id_idx" ON "auth"."sessions" USING "btree" ("oauth_client_id");



CREATE INDEX "sessions_user_id_idx" ON "auth"."sessions" USING "btree" ("user_id");



CREATE UNIQUE INDEX "sso_domains_domain_idx" ON "auth"."sso_domains" USING "btree" ("lower"("domain"));



CREATE INDEX "sso_domains_sso_provider_id_idx" ON "auth"."sso_domains" USING "btree" ("sso_provider_id");



CREATE UNIQUE INDEX "sso_providers_resource_id_idx" ON "auth"."sso_providers" USING "btree" ("lower"("resource_id"));



CREATE INDEX "sso_providers_resource_id_pattern_idx" ON "auth"."sso_providers" USING "btree" ("resource_id" "text_pattern_ops");



CREATE UNIQUE INDEX "unique_phone_factor_per_user" ON "auth"."mfa_factors" USING "btree" ("user_id", "phone");



CREATE INDEX "user_id_created_at_idx" ON "auth"."sessions" USING "btree" ("user_id", "created_at");



CREATE UNIQUE INDEX "users_email_partial_key" ON "auth"."users" USING "btree" ("email") WHERE ("is_sso_user" = false);



COMMENT ON INDEX "auth"."users_email_partial_key" IS 'Auth: A partial unique index that applies only when is_sso_user is false';



CREATE INDEX "users_instance_id_email_idx" ON "auth"."users" USING "btree" ("instance_id", "lower"(("email")::"text"));



CREATE INDEX "users_instance_id_idx" ON "auth"."users" USING "btree" ("instance_id");



CREATE INDEX "users_is_anonymous_idx" ON "auth"."users" USING "btree" ("is_anonymous");



CREATE INDEX "idx_ai_logs_order_sn" ON "public"."logs_execucao_ia" USING "btree" ("order_sn");



CREATE INDEX "idx_categoria_bom_regras_pai_id" ON "public"."categoria_bom_regras" USING "btree" ("categoria_pai_id");



CREATE INDEX "idx_config_entidade" ON "public"."configuracoes_aplicacao" USING "btree" ("entidade_tipo", "entidade_id");



CREATE INDEX "idx_config_nome" ON "public"."configuracoes_aplicacao" USING "btree" ("nome");



CREATE INDEX "idx_demandas_classificacao" ON "public"."demandas_producao" USING "btree" ("classificacao_cliente");



CREATE INDEX "idx_demandas_item_origem_demanda_item_id" ON "public"."demandas_item_origem" USING "btree" ("demanda_item_id");



CREATE INDEX "idx_demandas_item_origem_plataforma_pedido" ON "public"."demandas_item_origem" USING "btree" ("plataforma", "pedido_externo_id");



CREATE INDEX "idx_demandas_item_origem_sku_externo" ON "public"."demandas_item_origem" USING "btree" ("sku_externo");



CREATE INDEX "idx_demandas_modalidade" ON "public"."demandas_producao" USING "btree" ("modalidade_logistica");



CREATE INDEX "idx_demandas_producao_classificacao_cliente" ON "public"."demandas_producao" USING "btree" ("classificacao_cliente");



CREATE INDEX "idx_demandas_producao_modalidade_logistica" ON "public"."demandas_producao" USING "btree" ("modalidade_logistica");



CREATE INDEX "idx_entrega_producao_demanda_id" ON "public"."entrega_producao" USING "btree" ("demanda_id");



CREATE INDEX "idx_entrega_producao_item_id" ON "public"."entrega_producao" USING "btree" ("item_demanda_id");



CREATE INDEX "idx_estoque_atual_deposito_produto" ON "public"."estoque_atual" USING "btree" ("deposito_id", "produto_id");



CREATE INDEX "idx_estoque_atual_produto_deposito" ON "public"."estoque_atual" USING "btree" ("produto_id", "deposito_id");



CREATE INDEX "idx_feedback_order_sn" ON "public"."feedbacks_execucao_ia" USING "btree" ("order_sn");



CREATE INDEX "idx_ficha_tecnica_sku_comp" ON "public"."ficha_tecnica" USING "btree" ("sku_componente");



CREATE INDEX "idx_ficha_tecnica_sku_pai" ON "public"."ficha_tecnica" USING "btree" ("sku_produto_pai");



CREATE INDEX "idx_ident_alt_produto_id" ON "public"."identificadores_alternativos" USING "btree" ("produto_id");



CREATE INDEX "idx_ident_alt_tipo_valor" ON "public"."identificadores_alternativos" USING "btree" ("tipo_identificador", "valor_identificador");



CREATE INDEX "idx_logs_producao_diaria_data" ON "public"."logs_producao_diaria" USING "btree" ("data");



CREATE INDEX "idx_mensagem_chat_shopee_from_user" ON "public"."mensagem_chat_shopee" USING "btree" ("from_user_name");



CREATE INDEX "idx_mensagem_chat_shopee_to_user" ON "public"."mensagem_chat_shopee" USING "btree" ("to_user_name");



CREATE INDEX "idx_pedidos_bling_bling_id" ON "public"."pedidos_bling" USING "btree" ("bling_id");



CREATE INDEX "idx_pedidos_codigo_externo" ON "public"."pedidos" USING "btree" ("codigo_pedido_externo");



CREATE INDEX "idx_pedidos_shopee_codigo_pedido" ON "public"."pedidos_shopee" USING "btree" ("codigo_pedido");



CREATE INDEX "idx_personalizacoes_pedido_order_item" ON "public"."personalizacoes_pedido" USING "btree" ("shopee_order_sn", "item_description");



CREATE INDEX "idx_personalizacoes_shopee_sn" ON "public"."personalizacoes_pedido" USING "btree" ("shopee_order_sn");



CREATE INDEX "idx_pontos_coleta_ativo" ON "public"."pontos_coleta" USING "btree" ("ativo");



CREATE INDEX "idx_print_jobs_demanda_item_id" ON "public"."print_jobs" USING "btree" ("demanda_item_id");



CREATE INDEX "idx_print_jobs_status" ON "public"."print_jobs" USING "btree" ("status");



CREATE INDEX "idx_product_artworks_product_id" ON "public"."product_artworks" USING "btree" ("product_id");



CREATE INDEX "idx_produtos_atributos_status" ON "public"."produtos" USING "gin" ((("atributos" -> 'status'::"text")));



CREATE INDEX "idx_produtos_categoria_id" ON "public"."produtos" USING "btree" ("categoria_id");



CREATE INDEX "idx_produtos_estoque_minimo" ON "public"."produtos" USING "btree" ("estoque_minimo");



CREATE INDEX "idx_produtos_externos_codigo_externo" ON "public"."produtos_externos" USING "btree" ("codigo_externo");



CREATE INDEX "idx_produtos_externos_plataforma" ON "public"."produtos_externos" USING "btree" ("plataforma");



CREATE INDEX "idx_produtos_externos_produto_id" ON "public"."produtos_externos" USING "btree" ("produto_id");



CREATE INDEX "idx_produtos_formato" ON "public"."produtos" USING "btree" ("formato");



CREATE INDEX "idx_produtos_parent_id" ON "public"."produtos" USING "btree" ("parent_id");



CREATE INDEX "idx_produtos_preco_custo" ON "public"."produtos" USING "btree" ("preco_custo");



CREATE INDEX "idx_produtos_preco_venda" ON "public"."produtos" USING "btree" ("preco_venda");



CREATE INDEX "idx_produtos_setor_responsavel" ON "public"."produtos" USING "btree" ("setor_responsavel_id");



CREATE INDEX "idx_produtos_sku_pai" ON "public"."produtos" USING "btree" ("sku_pai");



CREATE INDEX "idx_produtos_status" ON "public"."produtos" USING "btree" ("status");



CREATE INDEX "idx_produtos_tipo_material" ON "public"."produtos" USING "btree" ("tipo_material");



CREATE INDEX "idx_produtos_unidade_medida_id" ON "public"."produtos" USING "btree" ("unidade_medida_id");



CREATE INDEX "idx_refresh_logs_created_at" ON "public"."integration_refresh_logs" USING "btree" ("created_at");



CREATE INDEX "idx_refresh_logs_integration" ON "public"."integration_refresh_logs" USING "btree" ("integration_id");



CREATE INDEX "idx_regras_canal_id" ON "public"."regras_logisticas_canal" USING "btree" ("canal_venda_id");



CREATE INDEX "idx_regras_modalidade" ON "public"."regras_logisticas_canal" USING "btree" ("modalidade");



CREATE INDEX "idx_system_events_log_category" ON "public"."system_events_log" USING "btree" ("category");



CREATE INDEX "idx_system_events_log_created" ON "public"."system_events_log" USING "btree" ("created_at");



CREATE INDEX "idx_system_events_log_reference" ON "public"."system_events_log" USING "btree" ("reference_id");



CREATE INDEX "idx_system_events_log_severity" ON "public"."system_events_log" USING "btree" ("severity");



CREATE INDEX "idx_vinculos_plataforma_id" ON "public"."vinculos_integracao_pedido" USING "btree" ("plataforma", "id_na_plataforma");



CREATE INDEX "idx_webhook_logs_created_at" ON "public"."webhook_logs" USING "btree" ("created_at");



CREATE INDEX "idx_webhook_logs_plataforma_status" ON "public"."webhook_logs" USING "btree" ("plataforma", "status");



CREATE UNIQUE INDEX "unique_default_deposito" ON "public"."depositos" USING "btree" ("is_default") WHERE ("is_default" = true);



CREATE UNIQUE INDEX "bname" ON "storage"."buckets" USING "btree" ("name");



CREATE UNIQUE INDEX "bucketid_objname" ON "storage"."objects" USING "btree" ("bucket_id", "name");



CREATE UNIQUE INDEX "buckets_analytics_unique_name_idx" ON "storage"."buckets_analytics" USING "btree" ("name") WHERE ("deleted_at" IS NULL);



CREATE INDEX "idx_multipart_uploads_list" ON "storage"."s3_multipart_uploads" USING "btree" ("bucket_id", "key", "created_at");



CREATE INDEX "idx_objects_bucket_id_name" ON "storage"."objects" USING "btree" ("bucket_id", "name" COLLATE "C");



CREATE INDEX "idx_objects_bucket_id_name_lower" ON "storage"."objects" USING "btree" ("bucket_id", "lower"("name") COLLATE "C");



CREATE INDEX "name_prefix_search" ON "storage"."objects" USING "btree" ("name" "text_pattern_ops");



CREATE UNIQUE INDEX "vector_indexes_name_bucket_id_idx" ON "storage"."vector_indexes" USING "btree" ("name", "bucket_id");



CREATE OR REPLACE TRIGGER "set_updated_at" BEFORE UPDATE ON "public"."configuracoes_aplicacao" FOR EACH ROW EXECUTE FUNCTION "public"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at" BEFORE UPDATE ON "public"."demandas_producao" FOR EACH ROW EXECUTE FUNCTION "public"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at" BEFORE UPDATE ON "public"."identificadores_alternativos" FOR EACH ROW EXECUTE FUNCTION "public"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "set_updated_at" BEFORE UPDATE ON "public"."produtos" FOR EACH ROW EXECUTE FUNCTION "public"."handle_updated_at"();



CREATE OR REPLACE TRIGGER "update_agenda_recursos_updated_at" BEFORE UPDATE ON "public"."agenda_recursos" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_canais_venda_updated_at" BEFORE UPDATE ON "public"."canais_venda" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_categorias_updated_at" BEFORE UPDATE ON "public"."categorias" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_componentes_ordem_producao_updated_at" BEFORE UPDATE ON "public"."componentes_ordem_producao" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_configuracoes_aplicacao_updated_at" BEFORE UPDATE ON "public"."configuracoes_aplicacao" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_contas_bling_updated_at" BEFORE UPDATE ON "public"."contas_bling" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_conversoes_uom_produto_updated_at" BEFORE UPDATE ON "public"."conversoes_uom_produto" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_demandas_producao_updated_at" BEFORE UPDATE ON "public"."demandas_producao" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_depositos_updated_at" BEFORE UPDATE ON "public"."depositos" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_entrega_producao_updated_at" BEFORE UPDATE ON "public"."entrega_producao" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_estoque_atual_updated_at" BEFORE UPDATE ON "public"."estoque_atual" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_eventos_auditoria_updated_at" BEFORE UPDATE ON "public"."eventos_auditoria" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_feedback_pedido_updated_at" BEFORE UPDATE ON "public"."feedback_pedido" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_ficha_tecnica_updated_at" BEFORE UPDATE ON "public"."ficha_tecnica" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_fornecedores_updated_at" BEFORE UPDATE ON "public"."fornecedores" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_identificadores_alternativos_updated_at" BEFORE UPDATE ON "public"."identificadores_alternativos" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_itens_demanda_updated_at" BEFORE UPDATE ON "public"."itens_demanda" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_itens_ordem_compra_updated_at" BEFORE UPDATE ON "public"."itens_ordem_compra" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_itens_pedido_bling_updated_at" BEFORE UPDATE ON "public"."itens_pedido_bling" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_itens_pedido_updated_at" BEFORE UPDATE ON "public"."itens_pedido" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_itens_venda_updated_at" BEFORE UPDATE ON "public"."itens_venda" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_logs_producao_diaria_updated_at" BEFORE UPDATE ON "public"."logs_producao_diaria" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_movimentacoes_estoque_updated_at" BEFORE UPDATE ON "public"."movimentacoes_estoque" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_notificacoes_updated_at" BEFORE UPDATE ON "public"."notificacoes" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_ordens_compra_updated_at" BEFORE UPDATE ON "public"."ordens_compra" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_ordens_producao_updated_at" BEFORE UPDATE ON "public"."ordens_producao" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_pedidos_bling_updated_at" BEFORE UPDATE ON "public"."pedidos_bling" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_pedidos_shopee_updated_at" BEFORE UPDATE ON "public"."pedidos_shopee" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_pedidos_updated_at" BEFORE UPDATE ON "public"."pedidos" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_permissoes_setor_updated_at" BEFORE UPDATE ON "public"."permissoes_setor" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_personalizacoes_pedido_updated_at" BEFORE UPDATE ON "public"."personalizacoes_pedido" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_plataformas_updated_at" BEFORE UPDATE ON "public"."plataformas" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_pontos_coleta_updated_at" BEFORE UPDATE ON "public"."pontos_coleta" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_print_jobs_updated_at" BEFORE UPDATE ON "public"."print_jobs" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_produtos_externos_updated_at" BEFORE UPDATE ON "public"."produtos_externos" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_produtos_updated_at" BEFORE UPDATE ON "public"."produtos" FOR EACH ROW EXECUTE FUNCTION "public"."update_produtos_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_recursos_produtivos_updated_at" BEFORE UPDATE ON "public"."recursos_produtivos" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_setores_updated_at" BEFORE UPDATE ON "public"."setores" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_situacoes_pedido_updated_at" BEFORE UPDATE ON "public"."situacoes_pedido" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_tags_updated_at" BEFORE UPDATE ON "public"."tags" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_transicoes_situacao_updated_at" BEFORE UPDATE ON "public"."transicoes_situacao" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_unidades_medida_updated_at" BEFORE UPDATE ON "public"."unidades_medida" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_usuarios_updated_at" BEFORE UPDATE ON "public"."usuarios" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_vendas_updated_at" BEFORE UPDATE ON "public"."vendas" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "update_vinculos_bling_updated_at" BEFORE UPDATE ON "public"."vinculos_bling" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at_column"();



CREATE OR REPLACE TRIGGER "enforce_bucket_name_length_trigger" BEFORE INSERT OR UPDATE OF "name" ON "storage"."buckets" FOR EACH ROW EXECUTE FUNCTION "storage"."enforce_bucket_name_length"();



CREATE OR REPLACE TRIGGER "protect_buckets_delete" BEFORE DELETE ON "storage"."buckets" FOR EACH STATEMENT EXECUTE FUNCTION "storage"."protect_delete"();



CREATE OR REPLACE TRIGGER "protect_objects_delete" BEFORE DELETE ON "storage"."objects" FOR EACH STATEMENT EXECUTE FUNCTION "storage"."protect_delete"();



CREATE OR REPLACE TRIGGER "update_objects_updated_at" BEFORE UPDATE ON "storage"."objects" FOR EACH ROW EXECUTE FUNCTION "storage"."update_updated_at_column"();



ALTER TABLE ONLY "auth"."identities"
    ADD CONSTRAINT "identities_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."mfa_amr_claims"
    ADD CONSTRAINT "mfa_amr_claims_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "auth"."sessions"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."mfa_challenges"
    ADD CONSTRAINT "mfa_challenges_auth_factor_id_fkey" FOREIGN KEY ("factor_id") REFERENCES "auth"."mfa_factors"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."mfa_factors"
    ADD CONSTRAINT "mfa_factors_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."oauth_authorizations"
    ADD CONSTRAINT "oauth_authorizations_client_id_fkey" FOREIGN KEY ("client_id") REFERENCES "auth"."oauth_clients"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."oauth_authorizations"
    ADD CONSTRAINT "oauth_authorizations_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."oauth_consents"
    ADD CONSTRAINT "oauth_consents_client_id_fkey" FOREIGN KEY ("client_id") REFERENCES "auth"."oauth_clients"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."oauth_consents"
    ADD CONSTRAINT "oauth_consents_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."one_time_tokens"
    ADD CONSTRAINT "one_time_tokens_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."refresh_tokens"
    ADD CONSTRAINT "refresh_tokens_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "auth"."sessions"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."saml_providers"
    ADD CONSTRAINT "saml_providers_sso_provider_id_fkey" FOREIGN KEY ("sso_provider_id") REFERENCES "auth"."sso_providers"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."saml_relay_states"
    ADD CONSTRAINT "saml_relay_states_flow_state_id_fkey" FOREIGN KEY ("flow_state_id") REFERENCES "auth"."flow_state"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."saml_relay_states"
    ADD CONSTRAINT "saml_relay_states_sso_provider_id_fkey" FOREIGN KEY ("sso_provider_id") REFERENCES "auth"."sso_providers"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."sessions"
    ADD CONSTRAINT "sessions_oauth_client_id_fkey" FOREIGN KEY ("oauth_client_id") REFERENCES "auth"."oauth_clients"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."sessions"
    ADD CONSTRAINT "sessions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "auth"."sso_domains"
    ADD CONSTRAINT "sso_domains_sso_provider_id_fkey" FOREIGN KEY ("sso_provider_id") REFERENCES "auth"."sso_providers"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."agenda_recursos"
    ADD CONSTRAINT "agenda_recursos_recurso_id_fkey" FOREIGN KEY ("recurso_id") REFERENCES "public"."recursos_produtivos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."canais_venda"
    ADD CONSTRAINT "canais_venda_conta_bling_id_fkey" FOREIGN KEY ("conta_bling_id") REFERENCES "public"."contas_bling"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."canais_venda"
    ADD CONSTRAINT "canais_venda_plataforma_id_fkey" FOREIGN KEY ("plataforma_id") REFERENCES "public"."plataformas"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."categoria_bom_regras"
    ADD CONSTRAINT "categoria_bom_regras_categoria_componente_id_fkey" FOREIGN KEY ("categoria_componente_id") REFERENCES "public"."categorias"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."categoria_bom_regras"
    ADD CONSTRAINT "categoria_bom_regras_categoria_pai_id_fkey" FOREIGN KEY ("categoria_pai_id") REFERENCES "public"."categorias"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."categorias"
    ADD CONSTRAINT "categorias_categoria_pai_id_fkey" FOREIGN KEY ("categoria_pai_id") REFERENCES "public"."categorias"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."componentes_ordem_producao"
    ADD CONSTRAINT "componentes_ordem_producao_componente_id_fkey" FOREIGN KEY ("componente_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."componentes_ordem_producao"
    ADD CONSTRAINT "componentes_ordem_producao_ordem_producao_id_fkey" FOREIGN KEY ("ordem_producao_id") REFERENCES "public"."ordens_producao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversoes_uom_produto"
    ADD CONSTRAINT "conversoes_uom_produto_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversoes_uom_produto"
    ADD CONSTRAINT "conversoes_uom_produto_unidade_destino_id_fkey" FOREIGN KEY ("unidade_destino_id") REFERENCES "public"."unidades_medida"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."conversoes_uom_produto"
    ADD CONSTRAINT "conversoes_uom_produto_unidade_origem_id_fkey" FOREIGN KEY ("unidade_origem_id") REFERENCES "public"."unidades_medida"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."demandas_item_origem"
    ADD CONSTRAINT "demandas_item_origem_demanda_item_id_fkey" FOREIGN KEY ("demanda_item_id") REFERENCES "public"."itens_demanda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_canal_venda_id_fkey" FOREIGN KEY ("canal_venda_id") REFERENCES "public"."canais_venda"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."demandas_producao"
    ADD CONSTRAINT "demandas_producao_responsavel_id_fkey" FOREIGN KEY ("responsavel_id") REFERENCES "public"."usuarios"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."entrega_producao"
    ADD CONSTRAINT "entrega_producao_demanda_id_fkey" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."entrega_producao"
    ADD CONSTRAINT "entrega_producao_item_demanda_id_fkey" FOREIGN KEY ("item_demanda_id") REFERENCES "public"."itens_demanda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."estoque_atual"
    ADD CONSTRAINT "estoque_atual_deposito_id_fkey" FOREIGN KEY ("deposito_id") REFERENCES "public"."depositos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."estoque_atual"
    ADD CONSTRAINT "estoque_atual_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."eventos_auditoria"
    ADD CONSTRAINT "eventos_auditoria_usuario_id_fkey" FOREIGN KEY ("usuario_id") REFERENCES "public"."usuarios"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."ficha_tecnica"
    ADD CONSTRAINT "ficha_tecnica_componente_id_fkey" FOREIGN KEY ("componente_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."ficha_tecnica"
    ADD CONSTRAINT "ficha_tecnica_produto_pai_id_fkey" FOREIGN KEY ("produto_pai_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."identificadores_alternativos"
    ADD CONSTRAINT "fk_produto" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produtos"
    ADD CONSTRAINT "fk_produtos_parent_id" FOREIGN KEY ("parent_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."fornecedor_insumos"
    ADD CONSTRAINT "fornecedor_insumos_fornecedor_id_fkey" FOREIGN KEY ("fornecedor_id") REFERENCES "public"."fornecedores"("id");



ALTER TABLE ONLY "public"."fornecedor_insumos"
    ADD CONSTRAINT "fornecedor_insumos_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id");



ALTER TABLE ONLY "public"."integration_refresh_logs"
    ADD CONSTRAINT "integration_refresh_logs_integration_id_fkey" FOREIGN KEY ("integration_id") REFERENCES "public"."installed_integrations"("id");



ALTER TABLE ONLY "public"."itens_demanda"
    ADD CONSTRAINT "itens_demanda_demanda_id_fkey" FOREIGN KEY ("demanda_id") REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."itens_demanda"
    ADD CONSTRAINT "itens_demanda_id_produto_miolo_fkey" FOREIGN KEY ("id_produto_miolo") REFERENCES "public"."produtos"("id");



ALTER TABLE ONLY "public"."itens_demanda"
    ADD CONSTRAINT "itens_demanda_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."itens_ordem_compra"
    ADD CONSTRAINT "itens_ordem_compra_ordem_compra_id_fkey" FOREIGN KEY ("ordem_compra_id") REFERENCES "public"."ordens_compra"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."itens_ordem_compra"
    ADD CONSTRAINT "itens_ordem_compra_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."itens_pedido_bling"
    ADD CONSTRAINT "itens_pedido_bling_pedido_bling_id_fkey" FOREIGN KEY ("pedido_bling_id") REFERENCES "public"."pedidos_bling"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."itens_pedido"
    ADD CONSTRAINT "itens_pedido_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."itens_pedido"
    ADD CONSTRAINT "itens_pedido_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id");



ALTER TABLE ONLY "public"."itens_venda"
    ADD CONSTRAINT "itens_venda_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."itens_venda"
    ADD CONSTRAINT "itens_venda_venda_id_fkey" FOREIGN KEY ("venda_id") REFERENCES "public"."vendas"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."logs_producao_diaria"
    ADD CONSTRAINT "logs_producao_diaria_equipe_id_fkey" FOREIGN KEY ("equipe_id") REFERENCES "public"."setores"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."logs_producao_diaria"
    ADD CONSTRAINT "logs_producao_diaria_ordem_producao_id_fkey" FOREIGN KEY ("ordem_producao_id") REFERENCES "public"."ordens_producao"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."logs_producao_diaria"
    ADD CONSTRAINT "logs_producao_diaria_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."movimentacoes_estoque"
    ADD CONSTRAINT "movimentacoes_estoque_deposito_id_fkey" FOREIGN KEY ("deposito_id") REFERENCES "public"."depositos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."movimentacoes_estoque"
    ADD CONSTRAINT "movimentacoes_estoque_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."movimentacoes_estoque"
    ADD CONSTRAINT "movimentacoes_estoque_usuario_id_fkey" FOREIGN KEY ("usuario_id") REFERENCES "public"."usuarios"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."ordens_compra"
    ADD CONSTRAINT "ordens_compra_fornecedor_id_fkey" FOREIGN KEY ("fornecedor_id") REFERENCES "public"."fornecedores"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."ordens_producao"
    ADD CONSTRAINT "ordens_producao_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."ordens_producao"
    ADD CONSTRAINT "ordens_producao_responsavel_id_fkey" FOREIGN KEY ("responsavel_id") REFERENCES "public"."usuarios"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."pedidos"
    ADD CONSTRAINT "pedidos_situacao_pedido_id_fkey" FOREIGN KEY ("situacao_pedido_id") REFERENCES "public"."situacoes_pedido"("id");



ALTER TABLE ONLY "public"."permissoes_setor"
    ADD CONSTRAINT "permissoes_setor_recurso_id_fkey" FOREIGN KEY ("recurso_id") REFERENCES "public"."recursos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."permissoes_setor"
    ADD CONSTRAINT "permissoes_setor_setor_id_fkey" FOREIGN KEY ("setor_id") REFERENCES "public"."setores"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."print_jobs"
    ADD CONSTRAINT "print_jobs_artwork_id_fkey" FOREIGN KEY ("artwork_id") REFERENCES "public"."product_artworks"("id");



ALTER TABLE ONLY "public"."print_jobs"
    ADD CONSTRAINT "print_jobs_demanda_item_id_fkey" FOREIGN KEY ("demanda_item_id") REFERENCES "public"."itens_demanda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."print_jobs"
    ADD CONSTRAINT "print_jobs_product_id_fkey" FOREIGN KEY ("product_id") REFERENCES "public"."produtos"("id");



ALTER TABLE ONLY "public"."product_artworks"
    ADD CONSTRAINT "product_artworks_product_id_fkey" FOREIGN KEY ("product_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produtos"
    ADD CONSTRAINT "produtos_categoria_id_fkey" FOREIGN KEY ("categoria_id") REFERENCES "public"."categorias"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."produtos_externos"
    ADD CONSTRAINT "produtos_externos_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."produtos"
    ADD CONSTRAINT "produtos_setor_responsavel_id_fkey" FOREIGN KEY ("setor_responsavel_id") REFERENCES "public"."setores"("id");



ALTER TABLE ONLY "public"."produtos"
    ADD CONSTRAINT "produtos_unidade_medida_id_fkey" FOREIGN KEY ("unidade_medida_id") REFERENCES "public"."unidades_medida"("id");



ALTER TABLE ONLY "public"."regras_logisticas_canal"
    ADD CONSTRAINT "regras_logisticas_canal_canal_venda_id_fkey" FOREIGN KEY ("canal_venda_id") REFERENCES "public"."canais_venda"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."regras_logisticas_canal"
    ADD CONSTRAINT "regras_logisticas_canal_ponto_coleta_id_fkey" FOREIGN KEY ("ponto_coleta_id") REFERENCES "public"."pontos_coleta"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."transicoes_situacao"
    ADD CONSTRAINT "transicoes_situacao_situacao_destino_id_fkey" FOREIGN KEY ("situacao_destino_id") REFERENCES "public"."situacoes_pedido"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."transicoes_situacao"
    ADD CONSTRAINT "transicoes_situacao_situacao_origem_id_fkey" FOREIGN KEY ("situacao_origem_id") REFERENCES "public"."situacoes_pedido"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."usuarios"
    ADD CONSTRAINT "usuarios_setor_id_fkey" FOREIGN KEY ("setor_id") REFERENCES "public"."setores"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."grupo_mensagens_chat_shopee"
    ADD CONSTRAINT "v2_bundle_messages_event_id_fkey" FOREIGN KEY ("event_id") REFERENCES "public"."mensagem_chat_shopee"("id");



ALTER TABLE ONLY "public"."vinculos_bling"
    ADD CONSTRAINT "vinculos_bling_produto_id_fkey" FOREIGN KEY ("produto_id") REFERENCES "public"."produtos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."vinculos_integracao_pedido"
    ADD CONSTRAINT "vinculos_integracao_pedido_pedido_id_fkey" FOREIGN KEY ("pedido_id") REFERENCES "public"."pedidos"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "storage"."objects"
    ADD CONSTRAINT "objects_bucketId_fkey" FOREIGN KEY ("bucket_id") REFERENCES "storage"."buckets"("id");



ALTER TABLE ONLY "storage"."s3_multipart_uploads"
    ADD CONSTRAINT "s3_multipart_uploads_bucket_id_fkey" FOREIGN KEY ("bucket_id") REFERENCES "storage"."buckets"("id");



ALTER TABLE ONLY "storage"."s3_multipart_uploads_parts"
    ADD CONSTRAINT "s3_multipart_uploads_parts_bucket_id_fkey" FOREIGN KEY ("bucket_id") REFERENCES "storage"."buckets"("id");



ALTER TABLE ONLY "storage"."s3_multipart_uploads_parts"
    ADD CONSTRAINT "s3_multipart_uploads_parts_upload_id_fkey" FOREIGN KEY ("upload_id") REFERENCES "storage"."s3_multipart_uploads"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "storage"."vector_indexes"
    ADD CONSTRAINT "vector_indexes_bucket_id_fkey" FOREIGN KEY ("bucket_id") REFERENCES "storage"."buckets_vectors"("id");



ALTER TABLE "auth"."audit_log_entries" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."flow_state" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."identities" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."instances" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."mfa_amr_claims" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."mfa_challenges" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."mfa_factors" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."one_time_tokens" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."refresh_tokens" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."saml_providers" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."saml_relay_states" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."schema_migrations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."sessions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."sso_domains" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."sso_providers" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "auth"."users" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "Allow authenticated read access" ON "public"."cache_dashboard_pedidos" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Allow authenticated read access" ON "public"."feedbacks_execucao_ia" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Allow authenticated read access" ON "public"."feedbacks_negativo" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Allow authenticated read access" ON "public"."logs_execucao_ia" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Allow authenticated read access" ON "public"."mensagem_chat_shopee" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Allow authenticated read access" ON "public"."personalizacoes_pedido" FOR SELECT TO "authenticated" USING (true);



CREATE POLICY "Enable read access for all users" ON "public"."integration_modules" FOR SELECT USING (true);



ALTER TABLE "public"."cache_dashboard_pedidos" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."feedbacks_execucao_ia" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."feedbacks_negativo" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."integration_modules" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."logs_execucao_ia" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."mensagem_chat_shopee" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."personalizacoes_pedido" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "storage"."buckets" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "storage"."buckets_analytics" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "storage"."buckets_vectors" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "storage"."migrations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "storage"."objects" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "storage"."s3_multipart_uploads" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "storage"."s3_multipart_uploads_parts" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "storage"."vector_indexes" ENABLE ROW LEVEL SECURITY;


GRANT USAGE ON SCHEMA "auth" TO "anon";
GRANT USAGE ON SCHEMA "auth" TO "authenticated";
GRANT USAGE ON SCHEMA "auth" TO "service_role";
GRANT ALL ON SCHEMA "auth" TO "supabase_auth_admin";
GRANT ALL ON SCHEMA "auth" TO "dashboard_user";
GRANT USAGE ON SCHEMA "auth" TO "postgres";



GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";



GRANT USAGE ON SCHEMA "storage" TO "postgres" WITH GRANT OPTION;
GRANT USAGE ON SCHEMA "storage" TO "anon";
GRANT USAGE ON SCHEMA "storage" TO "authenticated";
GRANT USAGE ON SCHEMA "storage" TO "service_role";
GRANT ALL ON SCHEMA "storage" TO "supabase_storage_admin" WITH GRANT OPTION;
GRANT ALL ON SCHEMA "storage" TO "dashboard_user";



GRANT ALL ON FUNCTION "auth"."email"() TO "dashboard_user";



GRANT ALL ON FUNCTION "auth"."jwt"() TO "postgres";
GRANT ALL ON FUNCTION "auth"."jwt"() TO "dashboard_user";



GRANT ALL ON FUNCTION "auth"."role"() TO "dashboard_user";



GRANT ALL ON FUNCTION "auth"."uid"() TO "dashboard_user";



GRANT ALL ON FUNCTION "public"."handle_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."handle_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."handle_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."standardize_table_timestamps"("target_table" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."standardize_table_timestamps"("target_table" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."standardize_table_timestamps"("target_table" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."update_produtos_updated_at_column"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_produtos_updated_at_column"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_produtos_updated_at_column"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_updated_at_column"() TO "service_role";



GRANT ALL ON TABLE "auth"."audit_log_entries" TO "dashboard_user";
GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."audit_log_entries" TO "postgres";
GRANT SELECT ON TABLE "auth"."audit_log_entries" TO "postgres" WITH GRANT OPTION;



GRANT ALL ON TABLE "auth"."custom_oauth_providers" TO "postgres";
GRANT ALL ON TABLE "auth"."custom_oauth_providers" TO "dashboard_user";



GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."flow_state" TO "postgres";
GRANT SELECT ON TABLE "auth"."flow_state" TO "postgres" WITH GRANT OPTION;
GRANT ALL ON TABLE "auth"."flow_state" TO "dashboard_user";



GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."identities" TO "postgres";
GRANT SELECT ON TABLE "auth"."identities" TO "postgres" WITH GRANT OPTION;
GRANT ALL ON TABLE "auth"."identities" TO "dashboard_user";



GRANT ALL ON TABLE "auth"."instances" TO "dashboard_user";
GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."instances" TO "postgres";
GRANT SELECT ON TABLE "auth"."instances" TO "postgres" WITH GRANT OPTION;



GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."mfa_amr_claims" TO "postgres";
GRANT SELECT ON TABLE "auth"."mfa_amr_claims" TO "postgres" WITH GRANT OPTION;
GRANT ALL ON TABLE "auth"."mfa_amr_claims" TO "dashboard_user";



GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."mfa_challenges" TO "postgres";
GRANT SELECT ON TABLE "auth"."mfa_challenges" TO "postgres" WITH GRANT OPTION;
GRANT ALL ON TABLE "auth"."mfa_challenges" TO "dashboard_user";



GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."mfa_factors" TO "postgres";
GRANT SELECT ON TABLE "auth"."mfa_factors" TO "postgres" WITH GRANT OPTION;
GRANT ALL ON TABLE "auth"."mfa_factors" TO "dashboard_user";



GRANT ALL ON TABLE "auth"."oauth_authorizations" TO "postgres";
GRANT ALL ON TABLE "auth"."oauth_authorizations" TO "dashboard_user";



GRANT ALL ON TABLE "auth"."oauth_client_states" TO "postgres";
GRANT ALL ON TABLE "auth"."oauth_client_states" TO "dashboard_user";



GRANT ALL ON TABLE "auth"."oauth_clients" TO "postgres";
GRANT ALL ON TABLE "auth"."oauth_clients" TO "dashboard_user";



GRANT ALL ON TABLE "auth"."oauth_consents" TO "postgres";
GRANT ALL ON TABLE "auth"."oauth_consents" TO "dashboard_user";



GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."one_time_tokens" TO "postgres";
GRANT SELECT ON TABLE "auth"."one_time_tokens" TO "postgres" WITH GRANT OPTION;
GRANT ALL ON TABLE "auth"."one_time_tokens" TO "dashboard_user";



GRANT ALL ON TABLE "auth"."refresh_tokens" TO "dashboard_user";
GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."refresh_tokens" TO "postgres";
GRANT SELECT ON TABLE "auth"."refresh_tokens" TO "postgres" WITH GRANT OPTION;



GRANT ALL ON SEQUENCE "auth"."refresh_tokens_id_seq" TO "dashboard_user";
GRANT ALL ON SEQUENCE "auth"."refresh_tokens_id_seq" TO "postgres";



GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."saml_providers" TO "postgres";
GRANT SELECT ON TABLE "auth"."saml_providers" TO "postgres" WITH GRANT OPTION;
GRANT ALL ON TABLE "auth"."saml_providers" TO "dashboard_user";



GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."saml_relay_states" TO "postgres";
GRANT SELECT ON TABLE "auth"."saml_relay_states" TO "postgres" WITH GRANT OPTION;
GRANT ALL ON TABLE "auth"."saml_relay_states" TO "dashboard_user";



GRANT SELECT ON TABLE "auth"."schema_migrations" TO "postgres" WITH GRANT OPTION;



GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."sessions" TO "postgres";
GRANT SELECT ON TABLE "auth"."sessions" TO "postgres" WITH GRANT OPTION;
GRANT ALL ON TABLE "auth"."sessions" TO "dashboard_user";



GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."sso_domains" TO "postgres";
GRANT SELECT ON TABLE "auth"."sso_domains" TO "postgres" WITH GRANT OPTION;
GRANT ALL ON TABLE "auth"."sso_domains" TO "dashboard_user";



GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."sso_providers" TO "postgres";
GRANT SELECT ON TABLE "auth"."sso_providers" TO "postgres" WITH GRANT OPTION;
GRANT ALL ON TABLE "auth"."sso_providers" TO "dashboard_user";



GRANT ALL ON TABLE "auth"."users" TO "dashboard_user";
GRANT INSERT,REFERENCES,DELETE,TRIGGER,TRUNCATE,MAINTAIN,UPDATE ON TABLE "auth"."users" TO "postgres";
GRANT SELECT ON TABLE "auth"."users" TO "postgres" WITH GRANT OPTION;



GRANT ALL ON TABLE "public"."agenda_recursos" TO "anon";
GRANT ALL ON TABLE "public"."agenda_recursos" TO "authenticated";
GRANT ALL ON TABLE "public"."agenda_recursos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."agenda_recursos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."agenda_recursos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."agenda_recursos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."logs_execucao_ia" TO "anon";
GRANT ALL ON TABLE "public"."logs_execucao_ia" TO "authenticated";
GRANT ALL ON TABLE "public"."logs_execucao_ia" TO "service_role";



GRANT ALL ON SEQUENCE "public"."ai_execution_logs_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."ai_execution_logs_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."ai_execution_logs_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."cache_dashboard_pedidos" TO "anon";
GRANT ALL ON TABLE "public"."cache_dashboard_pedidos" TO "authenticated";
GRANT ALL ON TABLE "public"."cache_dashboard_pedidos" TO "service_role";



GRANT ALL ON TABLE "public"."canais_venda" TO "anon";
GRANT ALL ON TABLE "public"."canais_venda" TO "authenticated";
GRANT ALL ON TABLE "public"."canais_venda" TO "service_role";



GRANT ALL ON SEQUENCE "public"."canais_venda_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."canais_venda_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."canais_venda_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."categoria_bom_regras" TO "anon";
GRANT ALL ON TABLE "public"."categoria_bom_regras" TO "authenticated";
GRANT ALL ON TABLE "public"."categoria_bom_regras" TO "service_role";



GRANT ALL ON SEQUENCE "public"."categoria_bom_regras_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."categoria_bom_regras_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."categoria_bom_regras_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."categorias" TO "anon";
GRANT ALL ON TABLE "public"."categorias" TO "authenticated";
GRANT ALL ON TABLE "public"."categorias" TO "service_role";



GRANT ALL ON SEQUENCE "public"."categorias_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."categorias_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."categorias_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."componentes_ordem_producao" TO "anon";
GRANT ALL ON TABLE "public"."componentes_ordem_producao" TO "authenticated";
GRANT ALL ON TABLE "public"."componentes_ordem_producao" TO "service_role";



GRANT ALL ON SEQUENCE "public"."componentes_ordem_producao_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."componentes_ordem_producao_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."componentes_ordem_producao_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."configuracoes_aplicacao" TO "anon";
GRANT ALL ON TABLE "public"."configuracoes_aplicacao" TO "authenticated";
GRANT ALL ON TABLE "public"."configuracoes_aplicacao" TO "service_role";



GRANT ALL ON SEQUENCE "public"."configuracoes_aplicacao_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."configuracoes_aplicacao_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."configuracoes_aplicacao_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."contas_bling" TO "anon";
GRANT ALL ON TABLE "public"."contas_bling" TO "authenticated";
GRANT ALL ON TABLE "public"."contas_bling" TO "service_role";



GRANT ALL ON SEQUENCE "public"."contas_bling_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."contas_bling_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."contas_bling_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."conversoes_uom_produto" TO "anon";
GRANT ALL ON TABLE "public"."conversoes_uom_produto" TO "authenticated";
GRANT ALL ON TABLE "public"."conversoes_uom_produto" TO "service_role";



GRANT ALL ON SEQUENCE "public"."conversoes_uom_produto_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."conversoes_uom_produto_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."conversoes_uom_produto_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."demandas_item_origem" TO "anon";
GRANT ALL ON TABLE "public"."demandas_item_origem" TO "authenticated";
GRANT ALL ON TABLE "public"."demandas_item_origem" TO "service_role";



GRANT ALL ON SEQUENCE "public"."demandas_item_origem_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."demandas_item_origem_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."demandas_item_origem_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."demandas_producao" TO "anon";
GRANT ALL ON TABLE "public"."demandas_producao" TO "authenticated";
GRANT ALL ON TABLE "public"."demandas_producao" TO "service_role";



GRANT ALL ON SEQUENCE "public"."demandas_producao_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."demandas_producao_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."demandas_producao_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."depositos" TO "anon";
GRANT ALL ON TABLE "public"."depositos" TO "authenticated";
GRANT ALL ON TABLE "public"."depositos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."depositos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."depositos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."depositos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."entrega_producao" TO "anon";
GRANT ALL ON TABLE "public"."entrega_producao" TO "authenticated";
GRANT ALL ON TABLE "public"."entrega_producao" TO "service_role";



GRANT ALL ON TABLE "public"."estoque_atual" TO "anon";
GRANT ALL ON TABLE "public"."estoque_atual" TO "authenticated";
GRANT ALL ON TABLE "public"."estoque_atual" TO "service_role";



GRANT ALL ON SEQUENCE "public"."estoque_atual_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."estoque_atual_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."estoque_atual_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."eventos_auditoria" TO "anon";
GRANT ALL ON TABLE "public"."eventos_auditoria" TO "authenticated";
GRANT ALL ON TABLE "public"."eventos_auditoria" TO "service_role";



GRANT ALL ON SEQUENCE "public"."eventos_auditoria_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."eventos_auditoria_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."eventos_auditoria_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."feedback_pedido" TO "anon";
GRANT ALL ON TABLE "public"."feedback_pedido" TO "authenticated";
GRANT ALL ON TABLE "public"."feedback_pedido" TO "service_role";



GRANT ALL ON SEQUENCE "public"."feedback_pedido_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."feedback_pedido_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."feedback_pedido_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."feedbacks_execucao_ia" TO "anon";
GRANT ALL ON TABLE "public"."feedbacks_execucao_ia" TO "authenticated";
GRANT ALL ON TABLE "public"."feedbacks_execucao_ia" TO "service_role";



GRANT ALL ON TABLE "public"."feedbacks_negativo" TO "anon";
GRANT ALL ON TABLE "public"."feedbacks_negativo" TO "authenticated";
GRANT ALL ON TABLE "public"."feedbacks_negativo" TO "service_role";



GRANT ALL ON TABLE "public"."ficha_tecnica" TO "anon";
GRANT ALL ON TABLE "public"."ficha_tecnica" TO "authenticated";
GRANT ALL ON TABLE "public"."ficha_tecnica" TO "service_role";



GRANT ALL ON SEQUENCE "public"."ficha_tecnica_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."ficha_tecnica_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."ficha_tecnica_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."fornecedor_insumos" TO "anon";
GRANT ALL ON TABLE "public"."fornecedor_insumos" TO "authenticated";
GRANT ALL ON TABLE "public"."fornecedor_insumos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."fornecedor_insumos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."fornecedor_insumos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."fornecedor_insumos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."fornecedores" TO "anon";
GRANT ALL ON TABLE "public"."fornecedores" TO "authenticated";
GRANT ALL ON TABLE "public"."fornecedores" TO "service_role";



GRANT ALL ON SEQUENCE "public"."fornecedores_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."fornecedores_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."fornecedores_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."grupo_mensagens_chat_shopee" TO "anon";
GRANT ALL ON TABLE "public"."grupo_mensagens_chat_shopee" TO "authenticated";
GRANT ALL ON TABLE "public"."grupo_mensagens_chat_shopee" TO "service_role";



GRANT ALL ON TABLE "public"."identificadores_alternativos" TO "anon";
GRANT ALL ON TABLE "public"."identificadores_alternativos" TO "authenticated";
GRANT ALL ON TABLE "public"."identificadores_alternativos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."identificadores_alternativos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."identificadores_alternativos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."identificadores_alternativos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."installed_integrations" TO "anon";
GRANT ALL ON TABLE "public"."installed_integrations" TO "authenticated";
GRANT ALL ON TABLE "public"."installed_integrations" TO "service_role";



GRANT ALL ON SEQUENCE "public"."installed_integrations_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."installed_integrations_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."installed_integrations_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."integration_modules" TO "anon";
GRANT ALL ON TABLE "public"."integration_modules" TO "authenticated";
GRANT ALL ON TABLE "public"."integration_modules" TO "service_role";



GRANT ALL ON TABLE "public"."integration_refresh_logs" TO "anon";
GRANT ALL ON TABLE "public"."integration_refresh_logs" TO "authenticated";
GRANT ALL ON TABLE "public"."integration_refresh_logs" TO "service_role";



GRANT ALL ON SEQUENCE "public"."integration_refresh_logs_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."integration_refresh_logs_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."integration_refresh_logs_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."itens_demanda" TO "anon";
GRANT ALL ON TABLE "public"."itens_demanda" TO "authenticated";
GRANT ALL ON TABLE "public"."itens_demanda" TO "service_role";



GRANT ALL ON SEQUENCE "public"."itens_demanda_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."itens_demanda_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."itens_demanda_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."itens_ordem_compra" TO "anon";
GRANT ALL ON TABLE "public"."itens_ordem_compra" TO "authenticated";
GRANT ALL ON TABLE "public"."itens_ordem_compra" TO "service_role";



GRANT ALL ON SEQUENCE "public"."itens_ordem_compra_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."itens_ordem_compra_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."itens_ordem_compra_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."itens_pedido" TO "anon";
GRANT ALL ON TABLE "public"."itens_pedido" TO "authenticated";
GRANT ALL ON TABLE "public"."itens_pedido" TO "service_role";



GRANT ALL ON TABLE "public"."itens_pedido_bling" TO "anon";
GRANT ALL ON TABLE "public"."itens_pedido_bling" TO "authenticated";
GRANT ALL ON TABLE "public"."itens_pedido_bling" TO "service_role";



GRANT ALL ON SEQUENCE "public"."itens_pedido_bling_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."itens_pedido_bling_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."itens_pedido_bling_id_seq" TO "service_role";



GRANT ALL ON SEQUENCE "public"."itens_pedido_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."itens_pedido_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."itens_pedido_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."itens_venda" TO "anon";
GRANT ALL ON TABLE "public"."itens_venda" TO "authenticated";
GRANT ALL ON TABLE "public"."itens_venda" TO "service_role";



GRANT ALL ON SEQUENCE "public"."itens_venda_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."itens_venda_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."itens_venda_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."logs_producao_diaria" TO "anon";
GRANT ALL ON TABLE "public"."logs_producao_diaria" TO "authenticated";
GRANT ALL ON TABLE "public"."logs_producao_diaria" TO "service_role";



GRANT ALL ON SEQUENCE "public"."logs_producao_diaria_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."logs_producao_diaria_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."logs_producao_diaria_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."mensagem_chat_shopee" TO "anon";
GRANT ALL ON TABLE "public"."mensagem_chat_shopee" TO "authenticated";
GRANT ALL ON TABLE "public"."mensagem_chat_shopee" TO "service_role";



GRANT ALL ON TABLE "public"."movimentacoes_estoque" TO "anon";
GRANT ALL ON TABLE "public"."movimentacoes_estoque" TO "authenticated";
GRANT ALL ON TABLE "public"."movimentacoes_estoque" TO "service_role";



GRANT ALL ON SEQUENCE "public"."movimentacoes_estoque_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."movimentacoes_estoque_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."movimentacoes_estoque_id_seq" TO "service_role";



GRANT ALL ON SEQUENCE "public"."negative_feedback_snapshots_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."negative_feedback_snapshots_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."negative_feedback_snapshots_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."notificacoes" TO "anon";
GRANT ALL ON TABLE "public"."notificacoes" TO "authenticated";
GRANT ALL ON TABLE "public"."notificacoes" TO "service_role";



GRANT ALL ON SEQUENCE "public"."notificacoes_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."notificacoes_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."notificacoes_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."ordens_compra" TO "anon";
GRANT ALL ON TABLE "public"."ordens_compra" TO "authenticated";
GRANT ALL ON TABLE "public"."ordens_compra" TO "service_role";



GRANT ALL ON SEQUENCE "public"."ordens_compra_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."ordens_compra_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."ordens_compra_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."ordens_producao" TO "anon";
GRANT ALL ON TABLE "public"."ordens_producao" TO "authenticated";
GRANT ALL ON TABLE "public"."ordens_producao" TO "service_role";



GRANT ALL ON SEQUENCE "public"."ordens_producao_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."ordens_producao_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."ordens_producao_id_seq" TO "service_role";



GRANT ALL ON SEQUENCE "public"."order_feedback_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."order_feedback_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."order_feedback_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pedidos" TO "anon";
GRANT ALL ON TABLE "public"."pedidos" TO "authenticated";
GRANT ALL ON TABLE "public"."pedidos" TO "service_role";



GRANT ALL ON TABLE "public"."pedidos_bling" TO "anon";
GRANT ALL ON TABLE "public"."pedidos_bling" TO "authenticated";
GRANT ALL ON TABLE "public"."pedidos_bling" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pedidos_bling_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pedidos_bling_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pedidos_bling_id_seq" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pedidos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pedidos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pedidos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pedidos_shopee" TO "anon";
GRANT ALL ON TABLE "public"."pedidos_shopee" TO "authenticated";
GRANT ALL ON TABLE "public"."pedidos_shopee" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pedidos_shopee_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pedidos_shopee_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pedidos_shopee_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."permissoes_setor" TO "anon";
GRANT ALL ON TABLE "public"."permissoes_setor" TO "authenticated";
GRANT ALL ON TABLE "public"."permissoes_setor" TO "service_role";



GRANT ALL ON SEQUENCE "public"."permissoes_setor_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."permissoes_setor_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."permissoes_setor_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."personalizacoes_pedido" TO "anon";
GRANT ALL ON TABLE "public"."personalizacoes_pedido" TO "authenticated";
GRANT ALL ON TABLE "public"."personalizacoes_pedido" TO "service_role";



GRANT ALL ON SEQUENCE "public"."personalizacoes_pedido_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."personalizacoes_pedido_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."personalizacoes_pedido_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."plataformas" TO "anon";
GRANT ALL ON TABLE "public"."plataformas" TO "authenticated";
GRANT ALL ON TABLE "public"."plataformas" TO "service_role";



GRANT ALL ON SEQUENCE "public"."plataformas_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."plataformas_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."plataformas_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."pontos_coleta" TO "anon";
GRANT ALL ON TABLE "public"."pontos_coleta" TO "authenticated";
GRANT ALL ON TABLE "public"."pontos_coleta" TO "service_role";



GRANT ALL ON SEQUENCE "public"."pontos_coleta_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."pontos_coleta_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."pontos_coleta_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."print_jobs" TO "anon";
GRANT ALL ON TABLE "public"."print_jobs" TO "authenticated";
GRANT ALL ON TABLE "public"."print_jobs" TO "service_role";



GRANT ALL ON SEQUENCE "public"."print_jobs_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."print_jobs_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."print_jobs_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."product_artworks" TO "anon";
GRANT ALL ON TABLE "public"."product_artworks" TO "authenticated";
GRANT ALL ON TABLE "public"."product_artworks" TO "service_role";



GRANT ALL ON SEQUENCE "public"."product_artworks_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."product_artworks_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."product_artworks_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."produtos" TO "anon";
GRANT ALL ON TABLE "public"."produtos" TO "authenticated";
GRANT ALL ON TABLE "public"."produtos" TO "service_role";



GRANT ALL ON TABLE "public"."produtos_externos" TO "anon";
GRANT ALL ON TABLE "public"."produtos_externos" TO "authenticated";
GRANT ALL ON TABLE "public"."produtos_externos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."produtos_externos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."produtos_externos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."produtos_externos_id_seq" TO "service_role";



GRANT ALL ON SEQUENCE "public"."produtos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."produtos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."produtos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."recursos" TO "anon";
GRANT ALL ON TABLE "public"."recursos" TO "authenticated";
GRANT ALL ON TABLE "public"."recursos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."recursos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."recursos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."recursos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."recursos_produtivos" TO "anon";
GRANT ALL ON TABLE "public"."recursos_produtivos" TO "authenticated";
GRANT ALL ON TABLE "public"."recursos_produtivos" TO "service_role";



GRANT ALL ON SEQUENCE "public"."recursos_produtivos_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."recursos_produtivos_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."recursos_produtivos_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."regras_logisticas_canal" TO "anon";
GRANT ALL ON TABLE "public"."regras_logisticas_canal" TO "authenticated";
GRANT ALL ON TABLE "public"."regras_logisticas_canal" TO "service_role";



GRANT ALL ON SEQUENCE "public"."regras_logisticas_canal_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."regras_logisticas_canal_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."regras_logisticas_canal_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."setores" TO "anon";
GRANT ALL ON TABLE "public"."setores" TO "authenticated";
GRANT ALL ON TABLE "public"."setores" TO "service_role";



GRANT ALL ON SEQUENCE "public"."setores_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."setores_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."setores_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."situacoes_pedido" TO "anon";
GRANT ALL ON TABLE "public"."situacoes_pedido" TO "authenticated";
GRANT ALL ON TABLE "public"."situacoes_pedido" TO "service_role";



GRANT ALL ON SEQUENCE "public"."situacoes_pedido_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."situacoes_pedido_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."situacoes_pedido_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."system_events_log" TO "anon";
GRANT ALL ON TABLE "public"."system_events_log" TO "authenticated";
GRANT ALL ON TABLE "public"."system_events_log" TO "service_role";



GRANT ALL ON TABLE "public"."tags" TO "anon";
GRANT ALL ON TABLE "public"."tags" TO "authenticated";
GRANT ALL ON TABLE "public"."tags" TO "service_role";



GRANT ALL ON SEQUENCE "public"."tags_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."tags_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."tags_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."transicoes_situacao" TO "anon";
GRANT ALL ON TABLE "public"."transicoes_situacao" TO "authenticated";
GRANT ALL ON TABLE "public"."transicoes_situacao" TO "service_role";



GRANT ALL ON SEQUENCE "public"."transicoes_situacao_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."transicoes_situacao_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."transicoes_situacao_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."unidades_medida" TO "anon";
GRANT ALL ON TABLE "public"."unidades_medida" TO "authenticated";
GRANT ALL ON TABLE "public"."unidades_medida" TO "service_role";



GRANT ALL ON SEQUENCE "public"."unidades_medida_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."unidades_medida_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."unidades_medida_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."usuarios" TO "anon";
GRANT ALL ON TABLE "public"."usuarios" TO "authenticated";
GRANT ALL ON TABLE "public"."usuarios" TO "service_role";



GRANT ALL ON SEQUENCE "public"."usuarios_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."usuarios_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."usuarios_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."vendas" TO "anon";
GRANT ALL ON TABLE "public"."vendas" TO "authenticated";
GRANT ALL ON TABLE "public"."vendas" TO "service_role";



GRANT ALL ON SEQUENCE "public"."vendas_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."vendas_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."vendas_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."view_consolidado_producao" TO "anon";
GRANT ALL ON TABLE "public"."view_consolidado_producao" TO "authenticated";
GRANT ALL ON TABLE "public"."view_consolidado_producao" TO "service_role";



GRANT ALL ON TABLE "public"."view_mensagens_chat" TO "anon";
GRANT ALL ON TABLE "public"."view_mensagens_chat" TO "authenticated";
GRANT ALL ON TABLE "public"."view_mensagens_chat" TO "service_role";



GRANT ALL ON TABLE "public"."view_vendas_personalizadas" TO "anon";
GRANT ALL ON TABLE "public"."view_vendas_personalizadas" TO "authenticated";
GRANT ALL ON TABLE "public"."view_vendas_personalizadas" TO "service_role";



GRANT ALL ON TABLE "public"."vinculos_integracao_pedido" TO "anon";
GRANT ALL ON TABLE "public"."vinculos_integracao_pedido" TO "authenticated";
GRANT ALL ON TABLE "public"."vinculos_integracao_pedido" TO "service_role";



GRANT ALL ON TABLE "public"."view_vendas_personalizadas_v3" TO "anon";
GRANT ALL ON TABLE "public"."view_vendas_personalizadas_v3" TO "authenticated";
GRANT ALL ON TABLE "public"."view_vendas_personalizadas_v3" TO "service_role";



GRANT ALL ON TABLE "public"."vinculos_bling" TO "anon";
GRANT ALL ON TABLE "public"."vinculos_bling" TO "authenticated";
GRANT ALL ON TABLE "public"."vinculos_bling" TO "service_role";



GRANT ALL ON SEQUENCE "public"."vinculos_bling_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."vinculos_bling_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."vinculos_bling_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."webhook_logs" TO "anon";
GRANT ALL ON TABLE "public"."webhook_logs" TO "authenticated";
GRANT ALL ON TABLE "public"."webhook_logs" TO "service_role";



GRANT ALL ON SEQUENCE "public"."webhook_logs_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."webhook_logs_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."webhook_logs_id_seq" TO "service_role";



REVOKE ALL ON TABLE "storage"."buckets" FROM "supabase_storage_admin";
GRANT ALL ON TABLE "storage"."buckets" TO "supabase_storage_admin" WITH GRANT OPTION;
GRANT ALL ON TABLE "storage"."buckets" TO "service_role";
GRANT ALL ON TABLE "storage"."buckets" TO "authenticated";
GRANT ALL ON TABLE "storage"."buckets" TO "anon";
GRANT ALL ON TABLE "storage"."buckets" TO "postgres" WITH GRANT OPTION;



GRANT ALL ON TABLE "storage"."buckets_analytics" TO "service_role";
GRANT ALL ON TABLE "storage"."buckets_analytics" TO "authenticated";
GRANT ALL ON TABLE "storage"."buckets_analytics" TO "anon";



GRANT SELECT ON TABLE "storage"."buckets_vectors" TO "service_role";
GRANT SELECT ON TABLE "storage"."buckets_vectors" TO "authenticated";
GRANT SELECT ON TABLE "storage"."buckets_vectors" TO "anon";



REVOKE ALL ON TABLE "storage"."objects" FROM "supabase_storage_admin";
GRANT ALL ON TABLE "storage"."objects" TO "supabase_storage_admin" WITH GRANT OPTION;
GRANT ALL ON TABLE "storage"."objects" TO "service_role";
GRANT ALL ON TABLE "storage"."objects" TO "authenticated";
GRANT ALL ON TABLE "storage"."objects" TO "anon";
GRANT ALL ON TABLE "storage"."objects" TO "postgres" WITH GRANT OPTION;



GRANT ALL ON TABLE "storage"."s3_multipart_uploads" TO "service_role";
GRANT SELECT ON TABLE "storage"."s3_multipart_uploads" TO "authenticated";
GRANT SELECT ON TABLE "storage"."s3_multipart_uploads" TO "anon";



GRANT ALL ON TABLE "storage"."s3_multipart_uploads_parts" TO "service_role";
GRANT SELECT ON TABLE "storage"."s3_multipart_uploads_parts" TO "authenticated";
GRANT SELECT ON TABLE "storage"."s3_multipart_uploads_parts" TO "anon";



GRANT SELECT ON TABLE "storage"."vector_indexes" TO "service_role";
GRANT SELECT ON TABLE "storage"."vector_indexes" TO "authenticated";
GRANT SELECT ON TABLE "storage"."vector_indexes" TO "anon";



ALTER DEFAULT PRIVILEGES FOR ROLE "supabase_auth_admin" IN SCHEMA "auth" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "supabase_auth_admin" IN SCHEMA "auth" GRANT ALL ON SEQUENCES TO "dashboard_user";



ALTER DEFAULT PRIVILEGES FOR ROLE "supabase_auth_admin" IN SCHEMA "auth" GRANT ALL ON FUNCTIONS TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "supabase_auth_admin" IN SCHEMA "auth" GRANT ALL ON FUNCTIONS TO "dashboard_user";



ALTER DEFAULT PRIVILEGES FOR ROLE "supabase_auth_admin" IN SCHEMA "auth" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "supabase_auth_admin" IN SCHEMA "auth" GRANT ALL ON TABLES TO "dashboard_user";



ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "storage" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "storage" GRANT ALL ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "storage" GRANT ALL ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "storage" GRANT ALL ON SEQUENCES TO "service_role";



ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "storage" GRANT ALL ON FUNCTIONS TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "storage" GRANT ALL ON FUNCTIONS TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "storage" GRANT ALL ON FUNCTIONS TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "storage" GRANT ALL ON FUNCTIONS TO "service_role";



ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "storage" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "storage" GRANT ALL ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "storage" GRANT ALL ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "storage" GRANT ALL ON TABLES TO "service_role";




