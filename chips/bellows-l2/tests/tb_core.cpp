#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Bytes = std::vector<uint8_t>;

Bytes unhex(const std::string& value) {
    if (value == "-") return {};
    if (value == "overflow") {
        Bytes bytes(0xffffffffULL / 255 + 2, 255);
        bytes.front() = 0xf0;
        bytes.back() = 0;
        return bytes;
    }
    if (value.size() % 2) throw std::runtime_error("odd hex field");
    Bytes bytes;
    bytes.reserve(value.size() / 2);
    for (size_t i = 0; i < value.size(); i += 2)
        bytes.push_back(static_cast<uint8_t>(std::stoul(value.substr(i, 2), nullptr, 16)));
    return bytes;
}

void hex(const Bytes& data) {
    static const char digits[] = "0123456789abcdef";
    if (data.empty()) std::cout << '-';
    for (unsigned byte : data) std::cout << digits[byte >> 4] << digits[byte & 15];
}

struct Channel {
    Bytes in, expected, actual;
    size_t sent = 0;
    int error = -1, held_data = -1, held_status = -1;
    bool presenting = false, done = false, last = false;
    unsigned in_stalls = 0, out_stalls = 0, status_stalls = 0;
};

struct Case {
    std::string name, mutation;
    unsigned mode = 0, rng = 0, flags = 0;
    unsigned capacity = 0, reset_cycles = 4;
    int bad_keep = -1;
    uint64_t cycles = 0, limit = 0;
    Channel c, d;
};

std::ifstream input;
std::unique_ptr<Case> job;
unsigned parameter;
bool completed = false;

[[noreturn]] void fail(const std::string& msg) {
    std::cerr << "CORE_ASSERT " << msg << " case=" << job->name << " cycle=" << job->cycles
              << " csent=" << job->c.sent << " dsent=" << job->d.sent
              << " cout=" << job->c.actual.size() << " dout=" << job->d.actual.size() << std::endl;
    std::exit(1);
}

void load(bool reset) {
    auto next = std::make_unique<Case>();
    std::string ci, co, di, dout;
    if (!(input >> next->name)) {
        if (!input.eof()) throw std::runtime_error("bad core scenario stream");
        completed = true;
        return;
    }
    if (!(input >> next->mode >> next->rng >> next->flags >> next->bad_keep >> next->mutation
          >> ci >> co >> next->c.error >> di >> dout >> next->d.error))
        throw std::runtime_error("incomplete core scenario");
    next->capacity = parameter;
    next->c.in = unhex(ci);
    next->c.expected = unhex(co);
    next->d.in = unhex(di);
    next->d.expected = unhex(dout);
    next->reset_cycles = reset ? 4 : 0;
    // Work is linear in accepted bytes plus the hash clear and bounded ready gaps.
    next->limit = 1024 + 80ULL * (next->c.in.size() + next->c.expected.size() +
                                 next->d.in.size() + next->d.expected.size() + 1);
    job = std::move(next);
}

unsigned next_random() {
    auto& x = job->rng;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    return x;
}

int drive(Channel& ch, bool enabled, bool is_compressor) {
    const auto n = ch.in.size();
    const auto count = is_compressor ? std::max<size_t>(1, n) : n;
    if (!enabled || ch.sent == count) return 0;
    const bool simultaneous_start = job->mode == 3 && !job->c.sent && !job->d.sent;
    if (!ch.presenting && !simultaneous_start && (next_random() & 3) == 0 && job->cycles % 8 != 0) return 0;
    ch.presenting = true;
    const bool keep = n && (!is_compressor || job->bad_keep != int(ch.sent));
    return (n ? ch.in[ch.sent] : 0) | (keep << 8) | (1 << 9) | ((ch.sent + 1 == count) << 10);
}

void sample(Channel& ch, int src, int ready, int response, int status, bool sink, bool status_ready,
            bool hides_output) {
    if (src & 512) {
        if (ready) {
            ++ch.sent;
            ch.presenting = false;
        } else {
            ++ch.in_stalls;
        }
    }
    if (ch.held_data >= 0 && ch.held_data != response) fail("stalled_output_stability");
    if (ch.held_status >= 0 && ch.held_status != status) fail("stalled_status_stability");
    ch.held_data = ch.held_status = -1;
    if (response & 512) {
        if (hides_output || ch.error < 0 || ch.last || ch.done) fail("unexpected_output");
        if (sink) {
            if (ch.actual.size() == ch.expected.size() && job->mutation == "-") fail("extra_output");
            ch.actual.push_back(response & 255);
            ch.last = (response & 1024) != 0;
        } else {
            ch.held_data = response;
            ++ch.out_stalls;
        }
    }
    if (status & 8) {
        if (ch.error < 0 || ch.done || (status & 7) != ch.error) fail("status_code");
        if (ch.held_data >= 0 || (!ch.actual.empty() && !ch.last)) fail("premature_status");
        if ((&ch == &job->c && ch.sent != std::max<size_t>(1, ch.in.size())) ||
            (&ch == &job->d && job->mode != 2 && ch.sent != ch.in.size())) fail("status_before_input_end");
        if (status_ready) ch.done = true;
        else {
            ch.held_status = status;
            ++ch.status_stalls;
        }
    }
}

// Inspect the recovered sequence layout before byte-exact comparison, so each
// deliberate mutant must reach its intended semantic assertion.
void inspect_encoding(const Bytes& data, size_t raw_size) {
    size_t i = 0, produced = 0;
    auto get = [&]() {
        if (i >= data.size()) fail("encoding_truncated");
        return unsigned(data[i++]);
    };
    auto length = [&](unsigned base) {
        size_t count = base;
        if (base == 15) {
            unsigned x;
            do { x = get(); count += x; } while (x == 255);
        }
        return count;
    };
    bool matched = false;
    while (i < data.size()) {
        const auto token = get();
        const auto literals = length(token >> 4);
        if (literals > data.size() - i) fail("encoding_truncated");
        i += literals;
        produced += literals;
        if (i == data.size()) {
            if (matched && literals < 5) fail("trailing_literals");
            if ((token & 15) || produced != raw_size) fail("encoding_decoded_length");
            return;
        }
        if (produced + 12 > raw_size) fail("match_start_limit");
        const auto low = get();
        const auto distance = low + 256 * get();
        if (distance == 0 || distance > produced) fail("invalid_match_offset");
        produced += 4 + length(token & 15);
        matched = true;
    }
    fail("trailing_literals");
}

int c_src, d_src, ctrl;
} // namespace

extern "C" void core_init(const char* path, int capacity) {
    parameter = capacity;
    input.open(path);
    if (!input) throw std::runtime_error("cannot open core scenarios");
    load(true);
    if (completed) throw std::runtime_error("empty core scenarios");
}

extern "C" void core_drive(int* c, int* d, int* control) {
    auto& j = *job;
    const bool active = j.reset_cycles == 0;
    const bool roundtrip = (j.mode == 2) != ((j.flags & 1) && (j.c.sent || j.d.sent));
    const bool c_sink = (j.cycles % 11 >= 6) && (next_random() & 3 || j.cycles % 11 == 10);
    const bool d_sink = (j.cycles % 13 >= 5) && (next_random() & 3 || j.cycles % 13 == 12);
    ctrl = active | (roundtrip << 1) | (c_sink << 2) | (d_sink << 3) |
           ((j.cycles % 7 == 6) << 4) | ((j.cycles % 7 == 6) << 5);
    c_src = active ? drive(j.c, j.c.error >= 0, true) : 0;
    d_src = active ? drive(j.d, j.mode == 1 || j.mode == 3, false) : 0;
    *c = c_src;
    *d = d_src;
    *control = ctrl;
}

extern "C" int core_sample(int c_out, int d_out, int c_ready, int d_ready, int c_status, int d_status) {
    auto& j = *job;
    if (++j.cycles > j.limit) fail("workload_cycle_guard");
    if (j.reset_cycles) {
        if ((c_out | d_out) & 512 || (c_status | d_status) & 8) fail("reset_ownership");
        --j.reset_cycles;
        return 0;
    }
    sample(j.c, c_src, c_ready, c_out, c_status, ctrl & 4, ctrl & 16, j.mode == 2);
    sample(j.d, d_src, d_ready, d_out, d_status, ctrl & 8, ctrl & 32, false);
    if ((j.flags & 2) && (j.c.held_data >= 0 || j.d.held_data >= 0)) {
        std::cout << "CORE_RESET " << j.name << ' ' << j.cycles << '\n';
        load(true);
        return completed;
    }
    if ((j.c.error >= 0 && !j.c.done) || (j.d.error >= 0 && !j.d.done)) return 0;
    if (j.flags & 2) fail("reset_stall_not_reached");
    if (j.c.error == 0 && j.mode != 2) inspect_encoding(j.c.actual, j.c.in.size());
    if (j.c.actual != j.c.expected || j.d.actual != j.d.expected) fail("byte_exact_output");
    std::cout << "CORE_PASS " << j.name << ' ' << j.capacity << ' ' << j.cycles << ' '
              << j.c.in_stalls << ' ' << j.d.in_stalls << ' ' << j.c.out_stalls << ' '
              << j.d.out_stalls << ' ' << j.c.status_stalls << ' ' << j.d.status_stalls << ' ';
    hex(j.c.actual);
    std::cout << '\n';
    load(false);
    return completed;
}
