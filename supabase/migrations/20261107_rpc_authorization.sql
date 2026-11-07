-- Sync-Lnk AI
-- RPC認可・実行権限対応
-- 2026-11-07
--
-- SECURITY DEFINER関数の本人確認・管理者確認と、
-- PUBLIC・anon・authenticatedのEXECUTE権限を管理する。

-- =========================================
-- 1. RPCの既定実行権限を削除
-- =========================================

revoke execute
on all functions in schema public
from public, anon;

-- =========================================
-- 2. 管理者用ユーザー一覧RPC
-- =========================================

create or replace function public.get_admin_user_list()
returns table (
    user_id text
)
language plpgsql
security definer
set search_path to ''
as $function$
begin
    if not exists (
        select 1
        from public.user_roles
        where user_roles.user_id = auth.uid()
          and user_roles.role = 'admin'
    ) then
        raise exception 'access denied';
    end if;

    return query
    select links.legacy_user_id
    from public.user_id_links as links
    order by links.legacy_user_id;
end;
$function$;

revoke execute
on function public.get_admin_user_list()
from public, anon;

grant execute
on function public.get_admin_user_list()
to authenticated;

-- =========================================
-- 3. 管理者用計算案件取得RPC
-- =========================================

create or replace function public.get_admin_calculation_cases(
    p_user_id text
)
returns setof public.calculation_cases
language plpgsql
security definer
set search_path to ''
as $function$
begin
    if not exists (
        select 1
        from public.user_roles
        where user_id = auth.uid()
          and role = 'admin'
    ) then
        raise exception 'access denied';
    end if;

    return query
    select cases.*
    from public.calculation_cases as cases
    where cases.user_id = p_user_id
    order by cases.created_at desc;
end;
$function$;

revoke execute
on function public.get_admin_calculation_cases(text)
from public, anon;

grant execute
on function public.get_admin_calculation_cases(text)
to authenticated;

-- =========================================
-- 4. 管理者用会話本文取得RPC
-- =========================================

create or replace function public.get_admin_user_messages(
    p_user_id text,
    p_message_id text
)
returns setof public.messages
language plpgsql
security definer
set search_path to ''
as $function$
begin
    if not exists (
        select 1
        from public.user_roles
        where user_id = auth.uid()
          and role = 'admin'
    ) then
        raise exception 'access denied';
    end if;

    return query
    select messages.*
    from public.messages
    where messages.user_id = p_user_id
      and messages.message_id = p_message_id
    order by messages.created_at;
end;
$function$;

revoke execute
on function public.get_admin_user_messages(text, text)
from public, anon;

grant execute
on function public.get_admin_user_messages(text, text)
to authenticated;

-- =========================================
-- 5. 管理者用個別監査ログ取得RPC
-- =========================================

create or replace function public.get_user_recent_audit_logs(
    p_user_id text,
    p_message_limit integer default 50
)
returns setof public.system_audit_logs
language plpgsql
security definer
set search_path to ''
as $function$
begin
    if not exists (
        select 1
        from public.user_roles
        where user_id = auth.uid()
          and role = 'admin'
    ) then
        raise exception 'access denied';
    end if;

    return query
    with recent_messages as (
        select
            logs.message_id,
            max(logs.created_at) as latest_created_at
        from public.system_audit_logs as logs
        where logs.user_id = p_user_id
          and logs.message_id is not null
          and logs.message_id <> ''
          and logs.event_type in (
              'CHAT_SUCCESS',
              'PLAN_CHAT_SUCCESS'
          )
        group by logs.message_id
        order by latest_created_at desc
        limit greatest(
            1,
            least(
                coalesce(p_message_limit, 50),
                300
            )
        )
    )
    select logs.*
    from public.system_audit_logs as logs
    inner join recent_messages
        on recent_messages.message_id = logs.message_id
    where logs.user_id = p_user_id
    order by logs.created_at desc;
end;
$function$;

revoke execute
on function public.get_user_recent_audit_logs(
    text,
    integer
)
from public, anon;

grant execute
on function public.get_user_recent_audit_logs(
    text,
    integer
)
to authenticated;

-- =========================================
-- 6. 管理者用システム監査集計RPC
-- =========================================

create or replace function public.get_system_audit_summary()
returns table (
    user_plan text,
    event_type text,
    event_count bigint,
    total_cost numeric,
    unique_user_count bigint,
    active_day_count bigint
)
language plpgsql
security definer
set search_path to ''
as $function$
begin
    if not exists (
        select 1
        from public.user_roles
        where user_id = auth.uid()
          and role = 'admin'
    ) then
        raise exception 'access denied';
    end if;

    return query
    select
        coalesce(logs.user_plan, '🆓 無料プラン'),
        coalesce(logs.event_type, ''),
        count(*),
        coalesce(sum(logs.total_yen_cost), 0)::numeric,
        count(distinct logs.user_id),
        count(
            distinct (
                logs.user_id::text || ':' ||
                (
                    logs.created_at
                    at time zone 'Asia/Tokyo'
                )::date::text
            )
        )
    from public.system_audit_logs as logs
    group by
        coalesce(logs.user_plan, '🆓 無料プラン'),
        coalesce(logs.event_type, '');
end;
$function$;

revoke execute
on function public.get_system_audit_summary()
from public, anon;

grant execute
on function public.get_system_audit_summary()
to authenticated;

-- =========================================
-- 7. 管理者用監査アクティビティ集計RPC
-- =========================================

create or replace function public.get_system_audit_activity_summary()
returns table (
    user_plan text,
    unique_user_count bigint,
    active_day_count bigint
)
language plpgsql
security definer
set search_path to ''
as $function$
begin
    if not exists (
        select 1
        from public.user_roles
        where user_id = auth.uid()
          and role = 'admin'
    ) then
        raise exception 'access denied';
    end if;

    return query
    select
        '__ALL__'::text,
        count(distinct logs.user_id),
        count(
            distinct (
                logs.user_id::text || ':' ||
                (
                    logs.created_at
                    at time zone 'Asia/Tokyo'
                )::date::text
            )
        )
    from public.system_audit_logs as logs

    union all

    select
        coalesce(
            logs.user_plan,
            '🆓 無料プラン'
        ),
        count(distinct logs.user_id),
        count(
            distinct (
                logs.user_id::text || ':' ||
                (
                    logs.created_at
                    at time zone 'Asia/Tokyo'
                )::date::text
            )
        )
    from public.system_audit_logs as logs
    group by
        coalesce(
            logs.user_plan,
            '🆓 無料プラン'
        );
end;
$function$;

revoke execute
on function public.get_system_audit_activity_summary()
from public, anon;

grant execute
on function public.get_system_audit_activity_summary()
to authenticated;

-- =========================================
-- 8. ユーザー別監査集計RPC
-- =========================================

create or replace function public.get_user_audit_summary(
    p_user_id text
)
returns table (
    normal_chat_count bigint,
    plan_chat_count bigint,
    plan_reflection_count bigint,
    active_day_count bigint,
    total_cost numeric,
    normal_chat_cost numeric,
    plan_chat_cost numeric,
    plan_reflection_cost numeric,
    normal_in_tokens bigint,
    normal_out_tokens bigint,
    plan_in_tokens bigint,
    plan_out_tokens bigint,
    plan_reflection_in_tokens bigint,
    plan_reflection_out_tokens bigint,
    normal_processing_time numeric,
    plan_processing_time numeric,
    plan_reflection_processing_time numeric
)
language sql
security definer
set search_path to ''
as $function$
    select
        count(*) filter (
            where logs.event_type = 'CHAT_SUCCESS'
        ),
        count(*) filter (
            where logs.event_type = 'PLAN_CHAT_SUCCESS'
        ),
        count(*) filter (
            where logs.event_type = 'PLAN_REFLECTION_SUCCESS'
        ),
        count(
            distinct (
                logs.created_at
                at time zone 'Asia/Tokyo'
            )::date
        ),
        coalesce(sum(logs.total_yen_cost), 0),
        coalesce(
            sum(logs.total_yen_cost) filter (
                where logs.event_type = 'CHAT_SUCCESS'
            ),
            0
        ),
        coalesce(
            sum(logs.total_yen_cost) filter (
                where logs.event_type = 'PLAN_CHAT_SUCCESS'
            ),
            0
        ),
        coalesce(
            sum(logs.total_yen_cost) filter (
                where logs.event_type = 'PLAN_REFLECTION_SUCCESS'
            ),
            0
        ),
        coalesce(
            sum(logs.in_tokens) filter (
                where logs.event_type = 'CHAT_SUCCESS'
            ),
            0
        )::bigint,
        coalesce(
            sum(logs.out_tokens) filter (
                where logs.event_type = 'CHAT_SUCCESS'
            ),
            0
        )::bigint,
        coalesce(
            sum(logs.in_tokens) filter (
                where logs.event_type = 'PLAN_CHAT_SUCCESS'
            ),
            0
        )::bigint,
        coalesce(
            sum(logs.out_tokens) filter (
                where logs.event_type = 'PLAN_CHAT_SUCCESS'
            ),
            0
        )::bigint,
        coalesce(
            sum(logs.in_tokens) filter (
                where logs.event_type = 'PLAN_REFLECTION_SUCCESS'
            ),
            0
        )::bigint,
        coalesce(
            sum(logs.out_tokens) filter (
                where logs.event_type = 'PLAN_REFLECTION_SUCCESS'
            ),
            0
        )::bigint,
        coalesce(
            sum(logs.processing_time) filter (
                where logs.event_type = 'CHAT_SUCCESS'
            ),
            0
        ),
        coalesce(
            sum(logs.processing_time) filter (
                where logs.event_type = 'PLAN_CHAT_SUCCESS'
            ),
            0
        ),
        coalesce(
            sum(logs.processing_time) filter (
                where logs.event_type = 'PLAN_REFLECTION_SUCCESS'
            ),
            0
        )
    from public.system_audit_logs as logs
    where logs.user_id = p_user_id
      and (
          exists (
              select 1
              from public.user_id_links
              where auth_user_id = auth.uid()
                and legacy_user_id = p_user_id
          )
          or exists (
              select 1
              from public.user_roles
              where user_id = auth.uid()
                and role = 'admin'
          )
      );
$function$;

revoke execute
on function public.get_user_audit_summary(text)
from public, anon;

grant execute
on function public.get_user_audit_summary(text)
to authenticated;

-- =========================================
-- 9. 本人の期限切れ権利処理RPC
-- =========================================

create or replace function public.expire_own_entitlements()
returns jsonb
language plpgsql
security definer
set search_path to ''
as $function$
declare
    v_legacy_user_id text;
    v_entitlement_count integer := 0;
    v_grant_count integer := 0;
begin
    select legacy_user_id
    into v_legacy_user_id
    from public.user_id_links
    where auth_user_id = auth.uid();

    if v_legacy_user_id is null then
        raise exception 'access denied';
    end if;

    update public.user_entitlements
    set
        status = 'expired',
        expiration_notified_at = now()
    where user_id = v_legacy_user_id
      and status = 'active'
      and expires_at is not null
      and expires_at <= now()
      and expiration_notified_at is null;

    get diagnostics v_entitlement_count = row_count;

    update public.user_entitlement_grants
    set
        status = 'expired',
        expiration_notified_at = now()
    where user_id = v_legacy_user_id
      and status = 'active'
      and expires_at is not null
      and expires_at <= now()
      and expiration_notified_at is null;

    get diagnostics v_grant_count = row_count;

    return jsonb_build_object(
        'entitlements_expired',
        v_entitlement_count,
        'grants_expired',
        v_grant_count
    );
end;
$function$;

revoke execute
on function public.expire_own_entitlements()
from public, anon;

grant execute
on function public.expire_own_entitlements()
to authenticated;

-- =========================================
-- 10. 設定保存RPCの実行権限
-- =========================================

revoke execute
on function public.save_all_user_settings_rpc(
    text,
    jsonb,
    boolean
)
from public, anon;

grant execute
on function public.save_all_user_settings_rpc(
    text,
    jsonb,
    boolean
)
to authenticated;

-- =========================================
-- 11. 主要RPCの実行権限
-- =========================================

grant execute
on function public.get_plan_overall_summary(text)
to authenticated;

grant execute
on function public.get_plan_project_count(text, text)
to authenticated;

drop function if exists
public.get_user_processing_type_summary(
    text,
    timestamp with time zone,
    timestamp with time zone
);

create function public.get_user_processing_type_summary(
    p_user_id text,
    p_start_at timestamp with time zone default null,
    p_end_at timestamp with time zone default null
)
returns table (
    processing_type text,
    execution_count bigint,
    total_in_tokens bigint,
    total_out_tokens bigint,
    total_processing_time double precision,
    average_processing_time double precision,
    total_api_cost numeric,
    router_yen_cost numeric,
    search_yen_cost numeric,
    answer_yen_cost numeric,
    total_yen_cost numeric,
    average_yen_cost numeric,
    maximum_yen_cost numeric
)
language plpgsql
stable
security definer
set search_path to ''
as $function$
begin
    if not exists (
        select 1
        from public.user_roles
        where user_id = auth.uid()
          and role = 'admin'
    ) then
        raise exception 'access denied';
    end if;

    return query
    with execution_rows as (
        -- 通常会話・簡易Analysis
        select
            coalesce(
                nullif(
                    trim(
                        substring(
                            chat.details
                            from '処理区分=([^|]+)'
                        )
                    ),
                    ''
                ),
                'unclassified'
            ) as processing_type,
            chat.message_id,
            coalesce(chat.in_tokens, 0)::bigint
                as in_tokens,
            coalesce(chat.out_tokens, 0)::bigint
                as out_tokens,
            coalesce(chat.processing_time, 0)::double precision
                as processing_time,
            coalesce(chat.api_cost, 0)::numeric
                as api_cost,
            coalesce(router.router_cost, 0)::numeric
                as router_cost,
            coalesce(search.search_cost, 0)::numeric
                as search_cost,
            coalesce(
                chat.total_yen_cost,
                chat.api_cost,
                0
            )::numeric as answer_cost
        from public.system_audit_logs as chat

        left join lateral (
            select
                sum(
                    coalesce(
                        router_log.total_yen_cost,
                        router_log.api_cost,
                        0
                    )
                )::numeric as router_cost
            from public.system_audit_logs as router_log
            where router_log.user_id = chat.user_id
              and router_log.message_id = chat.message_id
              and router_log.event_type in (
                  'RESPONSE_ROUTER',
                  'CALCULATION_TOOL_ROUTER'
              )
        ) as router on true

        left join lateral (
            select
                sum(
                    coalesce(
                        search_log.total_yen_cost,
                        search_log.api_cost,
                        0
                    )
                )::numeric as search_cost
            from public.system_audit_logs as search_log
            where search_log.user_id = chat.user_id
              and search_log.message_id = chat.message_id
              and search_log.event_type = 'SEARCH_EXECUTION'
        ) as search on true

        where chat.user_id = p_user_id
          and chat.event_type = 'CHAT_SUCCESS'
          and chat.details not like
              '%処理区分=simple_search%'
          and chat.details not like
              '%処理区分=real_estate_calculation%'
          and (
              p_start_at is null
              or chat.created_at >= p_start_at
          )
          and (
              p_end_at is null
              or chat.created_at < p_end_at
          )

        union all

        -- 簡易検索
        select
            'simple_search'::text,
            search_log.message_id,
            coalesce(search_log.in_tokens, 0)::bigint,
            coalesce(search_log.out_tokens, 0)::bigint,
            coalesce(
                search_log.processing_time,
                0
            )::double precision,
            coalesce(search_log.api_cost, 0)::numeric,
            coalesce(router.router_cost, 0)::numeric,
            coalesce(
                search_log.total_yen_cost,
                search_log.api_cost,
                0
            )::numeric,
            0::numeric
        from public.system_audit_logs as search_log

        left join lateral (
            select
                sum(
                    coalesce(
                        router_log.total_yen_cost,
                        router_log.api_cost,
                        0
                    )
                )::numeric as router_cost
            from public.system_audit_logs as router_log
            where router_log.user_id = search_log.user_id
              and router_log.message_id = search_log.message_id
              and router_log.event_type = 'RESPONSE_ROUTER'
        ) as router on true

        where search_log.user_id = p_user_id
          and search_log.event_type = 'SEARCH_EXECUTION'
          and search_log.details like
              '%処理区分=simple_search%'
          and (
              p_start_at is null
              or search_log.created_at >= p_start_at
          )
          and (
              p_end_at is null
              or search_log.created_at < p_end_at
          )

        union all

        -- 完了した不動産売却計算
        select
            'real_estate_calculation'::text,
            success.message_id,
            coalesce(extraction.in_tokens, 0)::bigint,
            coalesce(extraction.out_tokens, 0)::bigint,
            coalesce(
                extraction.processing_time,
                0
            )::double precision,
            coalesce(extraction.api_cost, 0)::numeric,
            coalesce(router.router_cost, 0)::numeric,
            0::numeric,
            coalesce(
                extraction.total_yen_cost,
                extraction.api_cost,
                0
            )::numeric
        from public.system_audit_logs as success

        left join public.system_audit_logs as extraction
          on extraction.user_id = success.user_id
         and extraction.message_id = success.message_id
         and extraction.event_type =
             'CALCULATION_EXTRACTION'

        left join lateral (
            select
                sum(
                    coalesce(
                        router_log.total_yen_cost,
                        router_log.api_cost,
                        0
                    )
                )::numeric as router_cost
            from public.system_audit_logs as router_log
            where router_log.user_id = success.user_id
              and router_log.message_id = success.message_id
              and router_log.event_type in (
                  'RESPONSE_ROUTER',
                  'CALCULATION_TOOL_ROUTER'
              )
        ) as router on true

        where success.user_id = p_user_id
          and success.event_type = 'CALCULATION_SUCCESS'
          and success.details like '%tool=real_estate_sale%'
          and (
              p_start_at is null
              or success.created_at >= p_start_at
          )
          and (
              p_end_at is null
              or success.created_at < p_end_at
          )
    ),
    calculated_rows as (
        select
            rows.*,
            (
                rows.router_cost
                + rows.search_cost
                + rows.answer_cost
            )::numeric as execution_total_cost
        from execution_rows as rows
    )
    select
        rows.processing_type,
        count(*)::bigint,
        sum(rows.in_tokens)::bigint,
        sum(rows.out_tokens)::bigint,
        sum(rows.processing_time)::double precision,
        avg(rows.processing_time)::double precision,
        sum(rows.api_cost)::numeric,
        sum(rows.router_cost)::numeric,
        sum(rows.search_cost)::numeric,
        sum(rows.answer_cost)::numeric,
        sum(rows.execution_total_cost)::numeric,
        avg(rows.execution_total_cost)::numeric,
        max(rows.execution_total_cost)::numeric
    from calculated_rows as rows
    group by rows.processing_type
    order by count(*) desc;
end;
$function$;

grant execute
on function public.get_user_processing_type_summary(
    text,
    timestamp with time zone,
    timestamp with time zone
)
to authenticated;

grant execute
on function public.get_active_entitlement_grant_total(
    text,
    text
)
to authenticated;

grant execute
on function public.cleanup_old_micro_chats(
    text,
    integer
)
to authenticated;

grant execute
on function public.match_messages(
    vector,
    double precision,
    integer,
    bigint,
    character varying
)
to authenticated;

grant execute
on function public.match_messages_all(
    vector,
    double precision,
    integer,
    text
)
to authenticated;

grant execute
on function public.match_messages_all(
    vector,
    double precision,
    integer,
    text,
    text[]
)
to authenticated;

grant execute
on function public.match_user_memories(
    vector,
    double precision,
    integer,
    text
)
to authenticated;

-- =========================================
-- 12. 未対応機能のRPCを停止
-- =========================================

revoke execute
on function public.check_reward_ad_eligibility(
    text,
    text
)
from public, anon, authenticated;

revoke execute
on function public.start_reward_ad_view(
    text,
    text,
    text
)
from public, anon, authenticated;

revoke execute
on function public.complete_reward_ad_view(
    text,
    text
)
from public, anon, authenticated;

revoke execute
on function public.purchase_point_product(
    text,
    text,
    text
)
from public, anon, authenticated;

revoke execute
on function public.earn_user_points(
    text,
    bigint,
    text,
    text,
    text,
    text,
    timestamp with time zone
)
from public, anon, authenticated;

-- =========================================
-- 13. ポイント消費RPCの本人確認
-- =========================================

do $$
begin
    if to_regprocedure(
        'public.use_user_points_internal(text,bigint,text,text,text,text)'
    ) is null then
        alter function public.use_user_points(
            text,
            bigint,
            text,
            text,
            text,
            text
        )
        rename to use_user_points_internal;
    end if;
end;
$$;

revoke execute
on function public.use_user_points_internal(
    text,
    bigint,
    text,
    text,
    text,
    text
)
from public, anon, authenticated;

create or replace function public.use_user_points(
    p_user_id text,
    p_points bigint,
    p_reason_code text,
    p_operation_id text,
    p_description text default null,
    p_reference_id text default null
)
returns table (
    result_status text,
    current_balance bigint,
    transaction_id bigint
)
language plpgsql
security definer
set search_path to ''
as $function$
begin
    if not exists (
        select 1
        from public.user_id_links
        where auth_user_id = auth.uid()
          and legacy_user_id = p_user_id
    ) then
        raise exception 'access denied';
    end if;

    return query
    select *
    from public.use_user_points_internal(
        p_user_id,
        p_points,
        p_reason_code,
        p_operation_id,
        p_description,
        p_reference_id
    );
end;
$function$;

revoke execute
on function public.use_user_points(
    text,
    bigint,
    text,
    text,
    text,
    text
)
from public, anon;

grant execute
on function public.use_user_points(
    text,
    bigint,
    text,
    text,
    text,
    text
)
to authenticated;

-- =========================================
-- 14. 関数のsearch_path固定
-- =========================================

alter function public.update_updated_at_column()
set search_path to '';

alter function public.get_user_processing_type_total_summary(
    text,
    timestamp with time zone,
    timestamp with time zone
)
set search_path to '';

alter function public.match_messages(
    vector,
    double precision,
    integer,
    bigint,
    character varying
)
set search_path to '';

alter function public.match_messages_all(
    vector,
    double precision,
    integer,
    text
)
set search_path to '';

alter function public.match_messages_all(
    vector,
    double precision,
    integer,
    text,
    text[]
)
set search_path to '';

alter function public.match_user_memories(
    vector,
    double precision,
    integer,
    text
)
set search_path to '';

-- =========================================
-- 15. 管理者用ユーザーKPI取得RPC
-- =========================================

create or replace function public.get_admin_user_kpi(
    p_user_id text
)
returns jsonb
language plpgsql
security definer
set search_path to ''
as $function$
declare
    result_data jsonb;
begin
    if not exists (
        select 1
        from public.user_roles
        where user_id = auth.uid()
          and role = 'admin'
    ) then
        raise exception 'access denied';
    end if;

    select jsonb_build_object(
        'start_date',
        (
            select min(created_at)
            from public.messages
            where user_id = p_user_id
        ),
        'last_date',
        (
            select max(created_at)
            from public.messages
            where user_id = p_user_id
        ),
        'search_count',
        (
            select count(*)
            from public.search_logs
            where user_id = p_user_id
        ),
        'search_judge_count',
        count(*) filter (
            where event_type = 'RESPONSE_ROUTER'
        ),
        'search_judge_total_cost',
        coalesce(
            sum(api_cost) filter (
                where event_type = 'RESPONSE_ROUTER'
            ),
            0
        ),
        'search_judge_total_in',
        coalesce(
            sum(in_tokens) filter (
                where event_type = 'RESPONSE_ROUTER'
            ),
            0
        ),
        'search_judge_total_out',
        coalesce(
            sum(out_tokens) filter (
                where event_type = 'RESPONSE_ROUTER'
            ),
            0
        ),
        'search_exec_count',
        count(*) filter (
            where event_type = 'SEARCH_EXECUTION'
        ),
        'search_exec_total_cost',
        coalesce(
            sum(api_cost) filter (
                where event_type = 'SEARCH_EXECUTION'
            ),
            0
        ),
        'search_exec_total_in',
        coalesce(
            sum(in_tokens) filter (
                where event_type = 'SEARCH_EXECUTION'
            ),
            0
        ),
        'search_exec_total_out',
        coalesce(
            sum(out_tokens) filter (
                where event_type = 'SEARCH_EXECUTION'
            ),
            0
        ),
        'calc_clarification_count',
        count(*) filter (
            where event_type =
                'general_calculation_clarification'
        ),
        'calc_clarification_cost',
        coalesce(
            sum(api_cost) filter (
                where event_type =
                    'general_calculation_clarification'
            ),
            0
        ),
        'calc_clarification_in',
        coalesce(
            sum(in_tokens) filter (
                where event_type =
                    'general_calculation_clarification'
            ),
            0
        ),
        'calc_clarification_out',
        coalesce(
            sum(out_tokens) filter (
                where event_type =
                    'general_calculation_clarification'
            ),
            0
        ),
        'calc_success',
        count(*) filter (
            where event_type = 'CALCULATION_SUCCESS'
        ),
        'calc_missing',
        count(*) filter (
            where event_type =
                'CALCULATION_MISSING_FIELDS'
        ),
        'calc_error',
        count(*) filter (
            where event_type = 'CALCULATION_ERROR'
        ),
        'calc_extract_cost',
        coalesce(
            sum(api_cost) filter (
                where event_type = 'CALCULATION_EXTRACTION'
            ),
            0
        ),
        'calc_extract_in',
        coalesce(
            sum(in_tokens) filter (
                where event_type = 'CALCULATION_EXTRACTION'
            ),
            0
        ),
        'calc_extract_out',
        coalesce(
            sum(out_tokens) filter (
                where event_type = 'CALCULATION_EXTRACTION'
            ),
            0
        )
    )
    into result_data
    from public.system_audit_logs
    where user_id = p_user_id;

    return result_data;
end;
$function$;

revoke execute
on function public.get_admin_user_kpi(text)
from public, anon;

grant execute
on function public.get_admin_user_kpi(text)
to authenticated;

-- =========================================
-- Security Advisor確認メモ
-- =========================================
--
-- authenticatedが実行可能なSECURITY DEFINER関数は、
-- 全件でauth.uid()による本人確認または管理者確認を実装済み。
-- 全件でsearch_pathを空文字に固定済み。
--
-- Security Advisorの
-- authenticated_security_definer_function_executable警告は、
-- 意図的に公開している認証済みユーザー向けRPCに対する警告。
