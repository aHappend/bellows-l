#include <cuda_runtime.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Byte = unsigned char;
using Bytes = std::vector<Byte>;
using Path = std::filesystem::path;
constexpr int Warp = 32, WarpsPerCta = 4, TableBits = 10, TableSize = 1 << TableBits;
constexpr unsigned AllLanes = 0xffffffffu;
constexpr int MaxBlock = 65536, Samples = 7;
constexpr std::array<int, 2> Batches{1, 1024};

__host__ __device__ int compress_bound(int size) {
    return size + size / 255 + 16;
}

__device__ unsigned read4(const Byte *src) {
    return unsigned(src[0]) | (unsigned(src[1]) << 8) | (unsigned(src[2]) << 16)
         | (unsigned(src[3]) << 24);
}

__device__ int extension_size(int length) {
    return length < 15 ? 0 : (length - 15) / 255 + 1;
}

__device__ void emit_extension(Byte *dst, int length, int bytes, int lane) {
    for (int i = lane; i < bytes; i += Warp)
        dst[i] = i == bytes - 1 ? (length - 15) % 255 : 255;
}

__device__ int emit_sequence(Byte *dst, int capacity, const Byte *src, int literals,
                             int distance, int match, int lane) {
    const int match_field = match ? match - 4 : 0;
    const int le = extension_size(literals), me = extension_size(match_field);
    const int size = 1 + le + literals + (match ? 2 + me : 0);
    if (size > capacity)
        return -1;
    if (lane == 0)
        dst[0] = (min(literals, 15) << 4) | min(match_field, 15);
    emit_extension(dst + 1, literals, le, lane);
    Byte *payload = dst + 1 + le;
    for (int i = lane; i < literals; i += Warp)
        payload[i] = src[i];
    if (match) {
        Byte *offset = payload + literals;
        if (lane == 0) {
            offset[0] = distance & 255;
            offset[1] = distance >> 8;
        }
        emit_extension(offset + 2, match_field, me, lane);
    }
    __syncwarp(AllLanes);
    return size;
}

__device__ int encode_block(const Byte *src, int size, Byte *dst, int capacity,
                            uint16_t *table, int lane) {
    for (int i = lane; i < TableSize; i += Warp)
        table[i] = 0;
    __syncwarp(AllLanes);
    const int all_literal = 1 + extension_size(size) + size;
    int start = 0, pos = 0, written = 0;
    while (pos <= size - 12) {
        int distance = 0;
        if (lane == 0) {
            for (; pos <= size - 12; ++pos) {
                const unsigned word = read4(src + pos);
                const unsigned key = (word * 2654435761u) >> (32 - TableBits);
                const int prev = int(table[key]) - 1;
                table[key] = pos + 1;
                if (prev >= 0 && pos - prev <= 65535 && read4(src + prev) == word) {
                    distance = pos - prev;
                    break;
                }
            }
        }
        pos = __shfl_sync(AllLanes, pos, 0);
        distance = __shfl_sync(AllLanes, distance, 0);
        if (!distance)
            break;
        int end = pos + 4;
        for (const int limit = size - 5; end < limit; end += Warp) {
            const int i = end + lane;
            const unsigned stop = __ballot_sync(AllLanes, i >= limit || src[i] != src[i - distance]);
            if (stop) {
                end += __ffs(stop) - 1;
                break;
            }
        }
        const int room = min(capacity, all_literal - 1) - written;
        const int emitted = emit_sequence(dst + written, room, src + start, pos - start,
                                          distance, end - pos, lane);
        if (emitted < 0)
            return emit_sequence(dst, capacity, src, size, 0, 0, lane);
        written += emitted;
        start = pos = end;
    }
    if (!written)
        return emit_sequence(dst, capacity, src, size, 0, 0, lane);
    const int room = min(capacity, all_literal - 1) - written;
    const int tail = emit_sequence(dst + written, room, src + start, size - start, 0, 0, lane);
    return tail < 0 ? emit_sequence(dst, capacity, src, size, 0, 0, lane) : written + tail;
}

__device__ bool read_extension(const Byte *src, int size, int &pos, int &length) {
    int value;
    do {
        if (pos == size)
            return false;
        value = src[pos++];
        length += value;
    } while (value == 255);
    return true;
}

struct Sequence {
    int payload, literals, distance, match, next;
};

__device__ Sequence parse(const Byte *src, int size, int pos, int written, int capacity) {
    const Sequence invalid{0, -1, 0, 0, 0};
    if (pos == size)
        return invalid;
    const int token = src[pos++];
    int literals = token >> 4;
    if ((literals == 15 && !read_extension(src, size, pos, literals))
        || literals > size - pos || literals > capacity - written)
        return invalid;
    const int payload = pos;
    pos += literals;
    if (pos == size)
        return {payload, literals, 0, 0, pos};
    if (size - pos < 2)
        return invalid;
    const int distance = src[pos] | (int(src[pos + 1]) << 8);
    pos += 2;
    int match = 4 + (token & 15);
    if (distance == 0 || distance > written + literals
        || (match == 19 && !read_extension(src, size, pos, match))
        || pos == size || match > capacity - written - literals)
        return invalid;
    return {payload, literals, distance, match, pos};
}

__device__ int decode_block(const Byte *src, int size, Byte *dst, int capacity, int lane) {
    int written = 0, pos = 0;
    for (;;) {
        Sequence seq{};
        if (lane == 0)
            seq = parse(src, size, pos, written, capacity);
        const int literals = __shfl_sync(AllLanes, seq.literals, 0);
        if (literals < 0)
            return -1;
        const int payload = __shfl_sync(AllLanes, seq.payload, 0);
        for (int i = lane; i < literals; i += Warp)
            dst[written + i] = src[payload + i];
        written += literals;
        const int distance = __shfl_sync(AllLanes, seq.distance, 0);
        if (!distance)
            return written;
        __syncwarp(AllLanes);
        const int match = __shfl_sync(AllLanes, seq.match, 0);
        const Byte *history = dst + written - distance;
        // Overlap repeats the already materialized prefix; no lane reads another lane's new copy.
        if (match <= distance) {
            for (int i = lane; i < match; i += Warp)
                dst[written + i] = history[i];
        } else {
            int idx = lane % distance;
            const int stride = Warp % distance;
            for (int i = lane; i < match; i += Warp) {
                dst[written + i] = history[idx];
                idx += stride;
                if (idx >= distance)
                    idx -= distance;
            }
        }
        __syncwarp(AllLanes);
        written += match;
        pos = __shfl_sync(AllLanes, seq.next, 0);
    }
}

template<bool Encode>
__global__ void codec(const Byte *src, int size, Byte *dst, int capacity, int *lengths, int batch) {
    const int warp = threadIdx.x / Warp, lane = threadIdx.x % Warp;
    const int block = blockIdx.x * WarpsPerCta + warp;
    if (block >= batch)
        return;
    src += size_t(block) * size;
    dst += size_t(block) * capacity;
    int result;
    if constexpr (Encode) {
        __shared__ uint16_t tables[WarpsPerCta][TableSize];
        result = encode_block(src, size, dst, capacity, tables[warp], lane);
    } else {
        result = decode_block(src, size, dst, capacity, lane);
    }
    if (lane == 0)
        lengths[block] = result;
}

void check(cudaError_t status, const char *operation) {
    if (status != cudaSuccess)
        throw std::runtime_error(std::string(operation) + ": " + cudaGetErrorString(status));
}
#define CUDA(call) check((call), #call)

template<typename T, bool Pinned>
struct Buffer {
    T *data;
    size_t bytes;
    explicit Buffer(size_t count) : bytes(count * sizeof(T)) {
        if constexpr (Pinned)
            CUDA(cudaMallocHost(&data, bytes));
        else
            CUDA(cudaMalloc(&data, bytes));
    }
    ~Buffer() {
        if constexpr (Pinned)
            cudaFreeHost(data);
        else
            cudaFree(data);
    }
    Buffer(const Buffer &) = delete;
    Buffer &operator=(const Buffer &) = delete;
};

struct Timing {
    int batch;
    size_t h2d_bytes, d2h_bytes;
    std::array<double, Samples> kernel_ms{}, inclusive_ms{};
};

template<bool Encode>
Bytes run_batch(cudaStream_t stream, const Bytes &input, int capacity, int batch,
                const Bytes *expected = nullptr, Timing *timing = nullptr) {
    const int size = static_cast<int>(input.size());
    Buffer<Byte, true> host_in(size_t(batch) * size), host_out(size_t(batch) * capacity);
    Buffer<int, true> host_lengths(batch);
    Buffer<Byte, false> dev_in(host_in.bytes), dev_out(host_out.bytes);
    Buffer<int, false> dev_lengths(batch);
    for (int i = 0; i < batch; ++i)
        std::copy(input.begin(), input.end(), host_in.data + size_t(i) * size);

    auto upload = [&] {
        CUDA(cudaMemcpyAsync(dev_in.data, host_in.data, host_in.bytes, cudaMemcpyHostToDevice, stream));
    };
    auto launch = [&] {
        const int grid = (batch + WarpsPerCta - 1) / WarpsPerCta;
        codec<Encode><<<grid, WarpsPerCta * Warp, 0, stream>>>(
            dev_in.data, size, dev_out.data, capacity, dev_lengths.data, batch);
        CUDA(cudaGetLastError());
    };
    auto download = [&] {
        CUDA(cudaMemcpyAsync(host_out.data, dev_out.data, host_out.bytes, cudaMemcpyDeviceToHost, stream));
        CUDA(cudaMemcpyAsync(host_lengths.data, dev_lengths.data, host_lengths.bytes,
                             cudaMemcpyDeviceToHost, stream));
    };
    auto invalidate_lengths = [&] {
        CUDA(cudaMemsetAsync(dev_lengths.data, 0xff, dev_lengths.bytes, stream));
    };
    auto validate = [&](const Bytes &wanted, const char *scope) {
        for (int i = 0; i < batch; ++i)
            if (host_lengths.data[i] != int(wanted.size())
                || !std::equal(wanted.begin(), wanted.end(), host_out.data + size_t(i) * capacity))
                throw std::runtime_error(std::string(scope) + ": incorrect length or bytes at batch index "
                                         + std::to_string(i));
    };

    invalidate_lengths();
    upload();
    launch();
    download();
    CUDA(cudaStreamSynchronize(stream));
    const int length = host_lengths.data[0];
    if (length <= 0 || length > capacity)
        throw std::runtime_error("CUDA codec failed (result length " + std::to_string(length) + ")");
    Bytes result(host_out.data, host_out.data + length);
    const Bytes &wanted = expected ? *expected : result;
    validate(wanted, "warmup");
    if (!timing)
        return result;

    timing->batch = batch;
    timing->h2d_bytes = host_in.bytes;
    timing->d2h_bytes = host_out.bytes + host_lengths.bytes;
    cudaEvent_t start, stop;
    CUDA(cudaEventCreate(&start));
    CUDA(cudaEventCreate(&stop));
    for (double &ms : timing->kernel_ms) {
        if (&ms == &timing->kernel_ms.back())
            invalidate_lengths();
        CUDA(cudaEventRecord(start, stream));
        launch();
        CUDA(cudaEventRecord(stop, stream));
        CUDA(cudaEventSynchronize(stop));
        float duration;
        CUDA(cudaEventElapsedTime(&duration, start, stop));
        ms = duration;
    }
    CUDA(cudaEventDestroy(start));
    CUDA(cudaEventDestroy(stop));
    download();
    CUDA(cudaStreamSynchronize(stream));
    validate(wanted, "kernel-only");

    for (double &ms : timing->inclusive_ms) {
        if (&ms == &timing->inclusive_ms.back()) {
            invalidate_lengths();
            CUDA(cudaStreamSynchronize(stream));
        }
        const auto begin = std::chrono::steady_clock::now();
        upload();
        launch();
        download();
        CUDA(cudaStreamSynchronize(stream));
        ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - begin).count();
    }
    validate(wanted, "transfer-inclusive");
    return result;
}

Bytes read_block(const Path &path, int max_size) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    const auto size = file.tellg();
    if (size <= 0 || size > max_size)
        throw std::runtime_error("Invalid input size: " + path.string());
    Bytes bytes(static_cast<size_t>(size));
    file.seekg(0);
    if (!file.read(reinterpret_cast<char *>(bytes.data()), size))
        throw std::runtime_error("Cannot read " + path.string());
    return bytes;
}

void write_block(const Path &path, const Bytes &bytes) {
    std::ofstream file(path, std::ios::binary);
    file.write(reinterpret_cast<const char *>(bytes.data()), bytes.size());
    file.close();
    if (!file)
        throw std::runtime_error("Cannot write " + path.string());
}

std::string uuid_string(const cudaUUID_t &uuid) {
    std::ostringstream s;
    s << "GPU-" << std::hex << std::setfill('0');
    for (int i = 0; i < 16; ++i) {
        if (i == 4 || i == 6 || i == 8 || i == 10)
            s << '-';
        s << std::setw(2) << unsigned(static_cast<Byte>(uuid.bytes[i]));
    }
    return s.str();
}

void print_samples(const std::array<double, Samples> &samples) {
    std::cout << '[';
    for (size_t i = 0; i < samples.size(); ++i)
        std::cout << (i ? "," : "") << samples[i];
    std::cout << ']';
}

template<bool Encode>
void measure(cudaStream_t stream, const Bytes &input, int capacity, const Bytes &expected) {
    std::cout << '[';
    for (int batch : Batches) {
        Timing timing{};
        run_batch<Encode>(stream, input, capacity, batch, &expected, &timing);
        std::cout << (batch == Batches.front() ? "" : ",")
                  << "{\"batch_size\":" << timing.batch << ",\"h2d_bytes_per_batch\":" << timing.h2d_bytes
                  << ",\"d2h_bytes_per_batch\":" << timing.d2h_bytes << ",\"kernel_only_ms\":";
        print_samples(timing.kernel_ms);
        std::cout << ",\"transfer_inclusive_ms\":";
        print_samples(timing.inclusive_ms);
        std::cout << '}';
    }
    std::cout << ']';
}
}  // namespace

int main(int argc, char **argv) {
    std::string active;
    try {
        if (argc < 3)
            throw std::runtime_error("Usage: matched_gpu <leased GPU UUID> <case directories...>");
        const char *visible = std::getenv("CUDA_VISIBLE_DEVICES");
        if (!visible || std::string(visible) != argv[1] || !std::getenv("VULCAN_COMPUTE_RESOURCE_CONTEXT"))
            throw std::runtime_error("Native CUDA runner requires the managed device binding");
        int devices;
        CUDA(cudaGetDeviceCount(&devices));
        if (devices != 1)
            throw std::runtime_error("Expected exactly one lease-visible CUDA device");
        cudaDeviceProp property{};
        CUDA(cudaGetDeviceProperties(&property, 0));
        const auto uuid = uuid_string(property.uuid);
        if (uuid != argv[1] || property.major != 7 || property.minor != 0
            || std::string(property.name).find("V100") == std::string::npos)
            throw std::runtime_error("Managed CUDA binding mismatch: CUDA selected " + uuid + " "
                                     + property.name + ", lease requires a V100 at " + argv[1]);
        CUDA(cudaSetDevice(0));
        int driver, runtime;
        CUDA(cudaDriverGetVersion(&driver));
        CUDA(cudaRuntimeGetVersion(&runtime));
        cudaStream_t stream;
        CUDA(cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking));
        std::cout << std::setprecision(12)
                  << "{\"device\":{\"gpu_uuid\":" << std::quoted(uuid)
                  << ",\"name\":" << std::quoted(property.name) << ",\"compute_capability\":\"7.0\""
                  << ",\"cuda_driver_version\":" << driver << ",\"cuda_runtime_version\":" << runtime
                  << "},\"blocks\":[";
        for (int i = 2; i < argc; ++i) {
            const Path dir(argv[i]);
            const auto id = dir.filename().string();
            const auto raw = read_block(dir / "raw.bin", MaxBlock);
            const auto common = read_block(dir / "common.lz4", compress_bound(MaxBlock));
            const int n = static_cast<int>(raw.size()), bound = compress_bound(n);
            active = id + " encode/recovery";
            const auto encoded = run_batch<true>(stream, raw, bound, 1);
            run_batch<false>(stream, encoded, n, 1, &raw);
            run_batch<false>(stream, common, n, 1, &raw);
            write_block(dir / "gpu.lz4", encoded);
            std::cout << (i == 2 ? "" : ",") << "{\"id\":" << std::quoted(id) << ",\"encode\":";
            active = id + " encode timing";
            measure<true>(stream, raw, bound, encoded);
            std::cout << ",\"decode_common\":";
            active = id + " common decode timing";
            measure<false>(stream, common, n, raw);
            std::cout << '}';
        }
        CUDA(cudaStreamDestroy(stream));
        std::cout << "]}\n";
        if (!std::cout)
            throw std::runtime_error("Cannot write CUDA measurements");
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "matched_gpu" << (active.empty() ? "" : " " + active) << ": " << error.what() << '\n';
        return 1;
    }
}
