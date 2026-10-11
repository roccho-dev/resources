/* Test-only linker observers. Original code, arguments and returns are unchanged.
 * No screenshot/text/cookie/URL bytes are recorded. Timing is observer-affected.
 */
#define _POSIX_C_SOURCE 200809L
#include "cdp.h"
#include <json-c/json.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

int __real_cdp_frame(Cdp *, Frame *);
int __real_cdp_apply(Cdp *, const Frame *, const Action *);
int __real_json_object_equal(struct json_object *, struct json_object *);
ssize_t __real_read(int, void *, size_t);
ssize_t __real_write(int, const void *, size_t);

static long long millis(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000LL + t.tv_nsec / 1000000;
}
static void record(const char *event, const char *fields, ...) {
    int saved = errno;
    static FILE *trace;
    static unsigned count;
    const char *path = getenv("CDP_TTY_TRACE");
    if (!path || count > 4096) { errno = saved; return; }
    if (!trace) trace = fopen(path, "a");
    if (trace) {
        if (count++ == 4096) {
            fprintf(trace, "{\"event\":\"trace-truncated\"}\n");
        } else {
            fprintf(trace, "{\"event\":\"%s\",\"mono_ms\":%lld", event, millis());
            va_list args;
            va_start(args, fields);
            vfprintf(trace, fields, args);
            va_end(args);
            fputs("}\n", trace);
        }
        fflush(trace);
    }
    errno = saved;
}
int __wrap_cdp_frame(Cdp *c, Frame *f) {
    long long begin = millis();
    record("frame.begin", "");
    int status = __real_cdp_frame(c, f);
    record("frame.end", ",\"status\":%d,\"elapsed_ms\":%lld", status, millis() - begin);
    return status;
}
int __wrap_cdp_apply(Cdp *c, const Frame *f, const Action *a) {
    long long begin = millis();
    record("apply.begin", ",\"kind\":%d", (int)a->kind);
    int status = __real_cdp_apply(c, f, a);
    record("apply.end", ",\"kind\":%d,\"status\":%d,\"elapsed_ms\":%lld",
           (int)a->kind, status, millis() - begin);
    return status;
}
static struct json_object *member(struct json_object *o, const char *key) {
    struct json_object *v = NULL;
    if (o) json_object_object_get_ex(o, key, &v);
    return v;
}
int __wrap_json_object_equal(struct json_object *a, struct json_object *b) {
    int equal = __real_json_object_equal(a, b);
    if (!equal && member(a, "visual") && member(b, "visual")) {
        const char *areas[] = {"visual", "layout", "view"};
        for (size_t i = 0; i < sizeof(areas)/sizeof(*areas); ++i) {
            struct json_object *old = member(a, areas[i]), *new = member(b, areas[i]);
            record("geometry.mismatch", ",\"area\":\"%s\",\"before\":%s,\"after\":%s",
                   areas[i], json_object_to_json_string_ext(old, JSON_C_TO_STRING_PLAIN),
                   json_object_to_json_string_ext(new, JSON_C_TO_STRING_PLAIN));
        }
        record("geometry.loader", ",\"changed\":%s",
               __real_json_object_equal(member(a, "loader"), member(b, "loader")) ? "false" : "true");
    }
    return equal;
}
ssize_t __wrap_read(int fd, void *bytes, size_t size) {
    ssize_t n = __real_read(fd, bytes, size);
    int saved = errno;
    if (fd == STDIN_FILENO && n > 0) {
        /* Retain only a bounded Kitty ACK token; fragmented reads are supported. */
        static char token[128];
        static size_t used;
        const unsigned char *input = bytes;
        record("tty.read", ",\"bytes\":%lld", (long long)n);
        for (ssize_t i = 0; i < n; ++i) {
            unsigned char ch = input[i];
            if (!used) { if (ch == 27) token[used++] = (char)ch; continue; }
            if (used == 1 && ch != '_') { used = ch == 27 ? 1 : 0; continue; }
            if (used == 2 && ch != 'G') { used = ch == 27 ? 1 : 0; continue; }
            if (used >= sizeof(token)-1) { record("ack-token-overflow", ""); used = 0; continue; }
            token[used++] = (char)ch;
            if (used >= 5 && token[used-2] == 27 && ch == '\\') {
                token[used-2] = 0;
                unsigned id = 0;
                char *result = strchr(token+3, ';');
                if (sscanf(token+3, "i=%u", &id) == 1 && result)
                    record("kitty.ack", ",\"image_id\":%u,\"ok\":%s", id,
                           strcmp(result+1, "OK") == 0 ? "true" : "false");
                used = 0;
            }
        }
    }
    errno = saved;
    return n;
}
ssize_t __wrap_write(int fd, const void *bytes, size_t size) {
    ssize_t n = __real_write(fd, bytes, size);
    int saved = errno;
    if (fd == STDOUT_FILENO)
        record("tty.write", ",\"requested\":%zu,\"written\":%lld,\"errno\":%d",
               size, (long long)n, n < 0 ? saved : 0);
    errno = saved;
    return n;
}

#ifdef OBSERVER_SELFTEST
#include <assert.h>
static int calls, outcome;
static Cdp *expected_c;
static Frame *expected_f;
static const Action *expected_a;
int __real_cdp_frame(Cdp *c, Frame *f) {
    assert(c == expected_c && f == expected_f);
    ++calls; errno = EAGAIN; return outcome;
}
int __real_cdp_apply(Cdp *c, const Frame *f, const Action *a) {
    assert(c == expected_c && f == expected_f && a == expected_a);
    ++calls; errno = EAGAIN; return outcome;
}
int main(void) {
    Frame f = {0}; Action a = {.kind = WHEEL};
    expected_c = NULL; expected_f = &f; expected_a = &a;
    for (outcome = 0; outcome <= 3; ++outcome) {
        calls = 0;
        assert(__wrap_cdp_frame(NULL, &f) == outcome && calls == 1 && errno == EAGAIN);
        assert(__wrap_cdp_apply(NULL, &f, &a) == outcome && calls == 2 && errno == EAGAIN);
    }
    json_object *x = json_tokener_parse("{\"visual\":{\"pageY\":0},\"layout\":{},\"view\":{},\"loader\":\"same\"}");
    json_object *y = json_tokener_parse("{\"visual\":{\"pageY\":80},\"layout\":{},\"view\":{},\"loader\":\"same\"}");
    assert(x && y);
    assert(__wrap_json_object_equal(x, x) == 1);
    assert(__wrap_json_object_equal(x, y) == 0);
    json_object_put(x); json_object_put(y);
    int channel[2]; assert(pipe(channel) == 0);
    assert(dup2(channel[0], STDIN_FILENO) == STDIN_FILENO);
    close(channel[0]);
    const char *parts[] = {"\033_", "Gi=91;", "OK\033\\"};
    for (size_t i = 0; i < 3; ++i) {
        char buf[32]; size_t n = strlen(parts[i]);
        assert(write(channel[1], parts[i], n) == (ssize_t)n);
        assert(__wrap_read(STDIN_FILENO, buf, n) == (ssize_t)n);
        assert(memcmp(buf, parts[i], n) == 0);
    }
    close(channel[1]);
    assert(__wrap_write(STDOUT_FILENO, "fixture", 7) == 7);
    return 0;
}
#endif
