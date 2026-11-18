SELECT public.ensure_user_day_partition(CURRENT_DATE - 2);
SELECT public.ensure_user_day_partition(CURRENT_DATE - 1);
SELECT public.ensure_user_day_partition(CURRENT_DATE);

INSERT INTO public."user_t" (username, password, email, created_on)
SELECT seed.username, seed.password, seed.email, seed.created_on
FROM (
    VALUES
        (1, 'martin', 'password', 'slavoff.martin@gmail.com', (CURRENT_DATE - 2)::TIMESTAMP),
        (2, 'test1', 'password', 'test1.test1@gmail.com', (CURRENT_DATE - 1)::TIMESTAMP),
        (3, 'test2', 'password', 'test2.test2@gmail.com', CURRENT_DATE::TIMESTAMP)
) AS seed(position, username, password, email, created_on)
WHERE NOT EXISTS (
    SELECT 1
    FROM public.user_identity AS ui
    WHERE ui.username = seed.username
       OR ui.email = seed.email
)
ORDER BY seed.position;
