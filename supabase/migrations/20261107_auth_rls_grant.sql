-- Sync-Lnk AI
-- Auth / RLS / GRANT / RPC認可対応
-- 2026-11-07
--
-- 注意:
-- このマイグレーションは既存DBへの対応内容を記録・再現するためのもの。

-- =========================================
-- 1. Auth UUIDと旧文字列IDの連携
-- =========================================

create table if not exists public.user_roles (
    user_id uuid primary key
        references auth.users(id) on delete cascade,
    role text not null
        check (role in ('admin', 'user')),
    created_at timestamptz not null default now()
);

create table if not exists public.user_id_links (
    auth_user_id uuid primary key
        references auth.users(id) on delete cascade,
    legacy_user_id text unique not null,
    created_at timestamptz not null default now()
);

alter table public.user_roles
enable row level security;

alter table public.user_id_links
enable row level security;

-- =========================================
-- 2. 認証連携テーブルのRLSポリシー
-- =========================================

drop policy if exists
    "users_can_read_own_role"
on public.user_roles;

create policy "users_can_read_own_role"
on public.user_roles
for select
to authenticated
using (
    user_id = auth.uid()
);

drop policy if exists
    "users_can_read_own_id_link"
on public.user_id_links;

create policy "users_can_read_own_id_link"
on public.user_id_links
for select
to authenticated
using (
    auth_user_id = auth.uid()
);

revoke all
on public.user_roles
from anon;

revoke all
on public.user_id_links
from anon;

revoke insert, update, delete
on public.user_roles
from authenticated;

revoke insert, update, delete
on public.user_id_links
from authenticated;

grant select
on public.user_roles
to authenticated;

grant select
on public.user_id_links
to authenticated;

-- =========================================
-- 3. messagesのRLSポリシー
-- =========================================

alter table public.messages
enable row level security;

drop policy if exists
    "users_can_read_own_messages"
on public.messages;

drop policy if exists
    "users_can_insert_own_messages"
on public.messages;

drop policy if exists
    "users_can_update_own_messages"
on public.messages;

drop policy if exists
    "users_can_delete_own_messages"
on public.messages;

create policy "users_can_read_own_messages"
on public.messages
for select
to authenticated
using (
    user_id = (
        select legacy_user_id
        from public.user_id_links
        where auth_user_id = auth.uid()
    )
);

create policy "users_can_insert_own_messages"
on public.messages
for insert
to authenticated
with check (
    user_id = (
        select legacy_user_id
        from public.user_id_links
        where auth_user_id = auth.uid()
    )
);

create policy "users_can_update_own_messages"
on public.messages
for update
to authenticated
using (
    user_id = (
        select legacy_user_id
        from public.user_id_links
        where auth_user_id = auth.uid()
    )
)
with check (
    user_id = (
        select legacy_user_id
        from public.user_id_links
        where auth_user_id = auth.uid()
    )
);

create policy "users_can_delete_own_messages"
on public.messages
for delete
to authenticated
using (
    user_id = (
        select legacy_user_id
        from public.user_id_links
        where auth_user_id = auth.uid()
    )
);

revoke all
on public.messages
from anon;

grant select, insert, update, delete
on public.messages
to authenticated;

-- =========================================
-- 4. system_audit_logsのRLSポリシー
-- =========================================

alter table public.system_audit_logs
enable row level security;

drop policy if exists
    "users_can_read_own_audit_logs"
on public.system_audit_logs;

drop policy if exists
    "users_can_insert_own_audit_logs"
on public.system_audit_logs;

create policy "users_can_read_own_audit_logs"
on public.system_audit_logs
for select
to authenticated
using (
    user_id = (
        select legacy_user_id
        from public.user_id_links
        where auth_user_id = auth.uid()
    )
);

create policy "users_can_insert_own_audit_logs"
on public.system_audit_logs
for insert
to authenticated
with check (
    user_id = (
        select legacy_user_id
        from public.user_id_links
        where auth_user_id = auth.uid()
    )
);

revoke all
on public.system_audit_logs
from anon;

grant select, insert
on public.system_audit_logs
to authenticated;

-- =========================================
-- 5. 全publicテーブルのRLS有効化
-- =========================================

do $$
declare
    target_table record;
begin
    for target_table in
        select tablename
        from pg_tables
        where schemaname = 'public'
    loop
        execute format(
            'alter table public.%I enable row level security',
            target_table.tablename
        );
    end loop;
end;
$$;

-- 匿名ユーザーの既存権限を削除
revoke all privileges
on all tables in schema public
from anon;

revoke all privileges
on all sequences in schema public
from anon;

revoke execute
on all functions in schema public
from public, anon;

-- =========================================
-- 6. 本人データ管理テーブルのRLSポリシー
-- =========================================

do $$
declare
    target_table text;
    target_policy text;
begin
    foreach target_table in array array[
        'calculation_cases',
        'plan_projects',
        'saved_chats',
        'user_memories',
        'user_memories_tester'
    ]
    loop
        target_policy :=
            'users_can_manage_own_' || target_table;

        execute format(
            'drop policy if exists %I on public.%I',
            target_policy,
            target_table
        );

        execute format(
            'create policy %I
             on public.%I
             for all
             to authenticated
             using (
                 user_id = (
                     select legacy_user_id
                     from public.user_id_links
                     where auth_user_id = auth.uid()
                 )
             )
             with check (
                 user_id = (
                     select legacy_user_id
                     from public.user_id_links
                     where auth_user_id = auth.uid()
                 )
             )',
            target_policy,
            target_table
        );

        execute format(
            'grant select, insert, update, delete
             on public.%I
             to authenticated',
            target_table
        );
    end loop;
end;
$$;

-- =========================================
-- 7. 本人参照専用テーブルのRLSポリシー
-- =========================================

do $$
declare
    target_table text;
    target_policy text;
begin
    foreach target_table in array array[
        'point_lots',
        'point_transactions',
        'reward_ad_views',
        'search_logs',
        'user_entitlement_grants',
        'user_entitlements',
        'user_point_balances',
        'user_subscriptions',
        'user_token_stats'
    ]
    loop
        target_policy :=
            'users_can_read_own_' || target_table;

        execute format(
            'drop policy if exists %I on public.%I',
            target_policy,
            target_table
        );

        execute format(
            'create policy %I
             on public.%I
             for select
             to authenticated
             using (
                 user_id = (
                     select legacy_user_id
                     from public.user_id_links
                     where auth_user_id = auth.uid()
                 )
             )',
            target_policy,
            target_table
        );

        execute format(
            'revoke insert, update, delete
             on public.%I
             from authenticated',
            target_table
        );

        execute format(
            'grant select
             on public.%I
             to authenticated',
            target_table
        );
    end loop;
end;
$$;

-- =========================================
-- 8. user_usage_limitsのRLSポリシー
-- =========================================

alter table public.user_usage_limits
enable row level security;

drop policy if exists
    "users_can_read_own_usage_limits"
on public.user_usage_limits;

drop policy if exists
    "users_can_insert_own_usage_limits"
on public.user_usage_limits;

drop policy if exists
    "users_can_update_own_usage_limits"
on public.user_usage_limits;

create policy "users_can_read_own_usage_limits"
on public.user_usage_limits
for select
to authenticated
using (
    user_id = (
        select legacy_user_id
        from public.user_id_links
        where auth_user_id = auth.uid()
    )
);

create policy "users_can_insert_own_usage_limits"
on public.user_usage_limits
for insert
to authenticated
with check (
    user_id = (
        select legacy_user_id
        from public.user_id_links
        where auth_user_id = auth.uid()
    )
);

create policy "users_can_update_own_usage_limits"
on public.user_usage_limits
for update
to authenticated
using (
    user_id = (
        select legacy_user_id
        from public.user_id_links
        where auth_user_id = auth.uid()
    )
)
with check (
    user_id = (
        select legacy_user_id
        from public.user_id_links
        where auth_user_id = auth.uid()
    )
);

grant select, insert, update
on public.user_usage_limits
to authenticated;

revoke delete
on public.user_usage_limits
from authenticated;

-- =========================================
-- 9. 共通商品・管理者専用テーブル
-- =========================================

drop policy if exists
    "authenticated_users_can_read_visible_point_products"
on public.point_products;

create policy
    "authenticated_users_can_read_visible_point_products"
on public.point_products
for select
to authenticated
using (
    is_enabled = true
    and is_visible = true
);

grant select
on public.point_products
to authenticated;

revoke insert, update, delete
on public.point_products
from authenticated;


drop policy if exists
    "admins_can_manage_error_analytics"
on public.app_error_analytics;

create policy "admins_can_manage_error_analytics"
on public.app_error_analytics
for all
to authenticated
using (
    exists (
        select 1
        from public.user_roles
        where user_id = auth.uid()
          and role = 'admin'
    )
)
with check (
    exists (
        select 1
        from public.user_roles
        where user_id = auth.uid()
          and role = 'admin'
    )
);

grant select, insert, update
on public.app_error_analytics
to authenticated;

revoke delete
on public.app_error_analytics
from authenticated;

-- =========================================
-- 10. 今後作成するDBオブジェクトの初期権限
-- =========================================

alter default privileges
for role postgres
in schema public
revoke all on tables from anon;

alter default privileges
for role postgres
in schema public
revoke all on sequences from anon;

alter default privileges
for role postgres
in schema public
revoke execute on functions from public, anon;

-- =========================================
-- 11. authenticatedのシーケンス権限
-- =========================================

grant usage, select
on all sequences in schema public
to authenticated;
