// Deterministic contact kernels. RNG, neighbor construction and stage control
// remain in Python. Compile without fast-math or floating-point contraction.
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <unordered_map>
#include <vector>

namespace py = pybind11;
using Floats = py::array_t<double, py::array::c_style>;
using Indices = py::array_t<std::int64_t, py::array::c_style>;

template <typename Array>
void aligned(const Array& array) {
    using T = typename Array::value_type;
    if (reinterpret_cast<std::uintptr_t>(array.data()) % alignof(T) != 0)
        throw py::value_error("Arrays must be aligned.");
}

void geometry_shape(const Floats& positions, const Floats& radii, const Floats& lengths) {
    if (positions.ndim() != 2 || positions.shape(1) != 3 || radii.ndim() != 1
        || positions.shape(0) != radii.shape(0) || lengths.ndim() != 1 || lengths.size() != 3)
        throw py::value_error("Expected positions (N, 3), radii (N,) and lengths (3,).");
    aligned(positions);
    aligned(radii);
    aligned(lengths);
}

struct Shift {
    std::int64_t i, j;
    std::array<double, 3> value;
};

// None requests a Python evaluation of coincident centers. No RNG is consumed
// here and no output buffers are changed before the entire block is inspected.
py::object evaluate_block(const Floats& positions, const Floats& radii,
                          const Floats& lengths, bool periodic,
                          const Indices& first, const Indices& second,
                          double max_overlap, bool relax_all_overlaps,
                          bool compute_energy, Floats correction, Indices degree) {
    geometry_shape(positions, radii, lengths);
    if (first.ndim() != 1 || second.ndim() != 1 || first.size() != second.size())
        throw py::value_error("Pair index arrays must have matching one-dimensional shapes.");
    aligned(first);
    aligned(second);
    aligned(correction);
    aligned(degree);
    const bool correcting = correction.size() != 0;
    if (correcting && (correction.ndim() != 2 || correction.shape(0) != radii.size()
                       || correction.shape(1) != 3 || degree.ndim() != 1 || degree.size() != radii.size()))
        throw py::value_error("Correction buffers do not match the particle population.");
    auto* corr = correcting ? correction.mutable_data() : nullptr;
    auto* counts = correcting ? degree.mutable_data() : nullptr;
    const auto* p = positions.data();
    const auto* r = radii.data();
    const auto* box = lengths.data();
    const auto* is = first.data();
    const auto* js = second.data();
    std::vector<Shift> shifts;
    std::vector<double> energies;
    if (correcting) shifts.reserve(first.size());
    if (compute_energy) energies.reserve(first.size());
    double maximum = 0.0, observed = 0.0;
    for (py::ssize_t pair = 0; pair < first.size(); ++pair) {
        const auto i = is[pair], j = js[pair];
        if (i < 0 || j < 0 || i >= radii.size() || j >= radii.size())
            throw py::value_error("Pair index is outside the particle population.");
        std::array<double, 3> delta;
        for (int axis = 0; axis < 3; ++axis) {
            delta[axis] = p[3*i+axis] - p[3*j+axis];
            if (periodic) delta[axis] -= box[axis] * std::nearbyint(delta[axis] / box[axis]);
        }
        const double squared = (delta[0]*delta[0] + delta[1]*delta[1]) + delta[2]*delta[2];
        const double sum = r[i] + r[j];
        if (squared > std::nextafter(sum*sum, std::numeric_limits<double>::infinity())) continue;
        const double distance = std::sqrt(squared);
        const double diameter = 2 * std::min(r[i], r[j]);
        const double overlap_distance = std::max(0.0, sum - distance);
        observed = std::max(observed, std::clamp((sum - distance) / diameter, 0.0, 1.0));
        if (max_overlap == 1.0) continue;
        const double excess = std::max(0.0, overlap_distance - max_overlap * diameter);
        maximum = std::max(maximum, excess / diameter);
        const double separation = relax_all_overlaps ? overlap_distance : excess;
        if (separation <= 0.0) continue;
        if (compute_energy) {
            const double normalized = separation / diameter;
            energies.push_back(normalized * normalized);
        }
        if (!correcting) continue;
        if (distance == 0.0) return py::none();
        Shift shift{i, j, {}};
        for (int axis = 0; axis < 3; ++axis)
            shift.value[axis] = (0.5 * separation) * (delta[axis] / distance);
        shifts.push_back(shift);
    }
    // Match the two np.add.at calls: all first endpoints, then all second
    // endpoints within each original 128-particle query block.
    for (const auto& shift : shifts) {
        for (int axis = 0; axis < 3; ++axis) corr[3*shift.i+axis] += shift.value[axis];
        ++counts[shift.i];
    }
    for (const auto& shift : shifts) {
        for (int axis = 0; axis < 3; ++axis) corr[3*shift.j+axis] += -shift.value[axis];
        ++counts[shift.j];
    }
    // NumPy retains its own reduction order for the energy/stagnation score.
    Floats energy_terms(energies.size());
    std::copy(energies.begin(), energies.end(), energy_terms.mutable_data());
    return py::make_tuple(maximum, observed, energy_terms);
}

class InsertionGrid {
    Floats positions_, radii_, lengths_;
    std::array<std::int64_t, 3> counts_;
    std::array<double, 3> widths_;
    bool periodic_;
    std::unordered_map<std::int64_t, std::vector<std::int64_t>> cells_;
    std::vector<bool> inserted_;

    std::int64_t key(const std::array<std::int64_t, 3>& cell) const {
        return (cell[0] * counts_[1] + cell[1]) * counts_[2] + cell[2];
    }

public:
    InsertionGrid(Floats positions, Floats radii, Floats lengths, Indices counts, bool periodic)
        : positions_(positions), radii_(radii), lengths_(lengths), periodic_(periodic) {
        geometry_shape(positions_, radii_, lengths_);
        positions_.mutable_data();
        if (counts.ndim() != 1 || counts.size() != 3)
            throw py::value_error("Cell counts must have shape (3,).");
        aligned(counts);
        for (int axis = 0; axis < 3; ++axis) {
            counts_[axis] = counts.data()[axis];
            if (counts_[axis] < 1 || counts_[axis] > 1000000
                || !std::isfinite(lengths_.data()[axis]) || lengths_.data()[axis] <= 0)
                throw py::value_error("Invalid cell counts or box lengths.");
            widths_[axis] = lengths_.data()[axis] / counts_[axis];
        }
        inserted_.resize(radii.size(), false);
    }

    std::pair<bool, double> try_insert(std::int64_t index, const Floats& candidate, double max_overlap) {
        if (index < 0 || index >= radii_.size() || inserted_[index])
            throw py::value_error("Invalid or already inserted particle index.");
        if (candidate.ndim() != 1 || candidate.size() != 3)
            throw py::value_error("Candidate must have shape (3,).");
        aligned(candidate);
        if (!std::isfinite(max_overlap) || max_overlap < 0 || max_overlap > 1)
            throw py::value_error("Invalid maximum overlap.");
        const auto* point = candidate.data();
        const auto* lengths = lengths_.data();
        const auto* radii = radii_.data();
        auto* positions = positions_.mutable_data();
        std::array<std::int64_t, 3> cell;
        std::array<std::vector<std::int64_t>, 3> neighbors;
        for (int axis = 0; axis < 3; ++axis) {
            if (!std::isfinite(point[axis]) || point[axis] < 0 || point[axis] > lengths[axis])
                throw py::value_error("Candidate is outside the box.");
            cell[axis] = std::min(static_cast<std::int64_t>(point[axis] / widths_[axis]), counts_[axis] - 1);
            for (int offset = -1; offset <= 1; ++offset) {
                auto value = cell[axis] + offset;
                if (periodic_) value = (value + counts_[axis]) % counts_[axis];
                else if (value < 0 || value >= counts_[axis]) continue;
                neighbors[axis].push_back(value);
            }
            std::sort(neighbors[axis].begin(), neighbors[axis].end());
            neighbors[axis].erase(std::unique(neighbors[axis].begin(), neighbors[axis].end()), neighbors[axis].end());
        }
        double observed = 0.0;
        for (const auto x : neighbors[0]) for (const auto y : neighbors[1]) for (const auto z : neighbors[2]) {
            const auto found = cells_.find(key({x, y, z}));
            if (found == cells_.end()) continue;
            for (const auto other : found->second) {
                std::array<double, 3> delta;
                for (int axis = 0; axis < 3; ++axis) {
                    delta[axis] = std::abs(positions[3*other+axis] - point[axis]);
                    if (periodic_) delta[axis] = std::min(delta[axis], lengths[axis] - delta[axis]);
                }
                const double squared = (delta[0]*delta[0] + delta[1]*delta[1]) + delta[2]*delta[2];
                const double sum = radii[index] + radii[other];
                const double minimum = std::min(radii[index], radii[other]);
                if (max_overlap < 1.0) {
                    const double required = sum - (2 * max_overlap) * minimum;
                    const double safe = std::max(0.0, required - 16 * std::numeric_limits<double>::epsilon() * sum);
                    if (squared < safe*safe) return {false, 0.0};
                }
                const double overlap = std::clamp((sum - std::sqrt(squared)) / (2 * minimum), 0.0, 1.0);
                if (overlap > max_overlap) return {false, 0.0};
                observed = std::max(observed, overlap);
            }
        }
        cells_[key(cell)].push_back(index);
        inserted_[index] = true;
        for (int axis = 0; axis < 3; ++axis) positions[3*index+axis] = point[axis];
        return {true, observed};
    }
};

PYBIND11_MODULE(_kernels, module) {
    module.doc() = "Native deterministic particle contact kernels";
    module.def("evaluate_block", &evaluate_block,
               py::arg("positions").noconvert(), py::arg("radii").noconvert(),
               py::arg("lengths").noconvert(), py::arg("periodic"),
               py::arg("first").noconvert(), py::arg("second").noconvert(),
               py::arg("max_overlap"), py::arg("relax_all_overlaps"), py::arg("compute_energy"),
               py::arg("correction").noconvert(), py::arg("degree").noconvert());
    py::class_<InsertionGrid>(module, "InsertionGrid")
        .def(py::init<Floats, Floats, Floats, Indices, bool>(),
             py::arg("positions").noconvert(), py::arg("radii").noconvert(),
             py::arg("lengths").noconvert(), py::arg("counts").noconvert(), py::arg("periodic"))
        .def("try_insert", &InsertionGrid::try_insert, py::arg("index"),
             py::arg("candidate").noconvert(), py::arg("max_overlap"));
}
