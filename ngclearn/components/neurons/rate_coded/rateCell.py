from ngclib.component import Component
from jax import numpy as jnp, random, jit, nn
from functools import partial
from ngclearn.utils.model_utils import create_function
import time, sys

@jit
def modulate(j, dfx_val):
    return j * dfx_val

@partial(jit, static_argnums=[4,5,6])
def run_cell(dt, j, j_td, z, tau_m, leak_gamma=0., beta=1.):
    """
    Runs leaky rate-coded state dynamics.
    """
    dz_dt = (-z * leak_gamma + (j + j_td))
    _z = z * beta + dz_dt * (dt/tau_m)
    return _z

@jit
def run_cell_stateless(j):
    return j + 0

class RateCell(Component): ## Rate-coded/real-valued cell
    ## Class Methods for Compartment Names
    @classmethod
    def inputCompartmentName(cls):
        return 'j' ## electrical current

    @classmethod
    def outputCompartmentName(cls): # OR: activityName()
        return 'zF' ## rate-coded output

    @classmethod
    def pressureName(cls):
        return 'j_td'

    @classmethod
    def rateActivityName(cls):
        return 'z'

    ## Bind Properties to Compartments for ease of use
    @property
    def current(self):
        return self.compartments.get(self.inputCompartmentName(), None)

    @current.setter
    def current(self, inp):
        if inp is not None:
            if inp.shape[1] != self.n_units:
                raise RuntimeError(
                    "Input current compartment size does not match provided input size " + str(inp.shape) + "for "
                    + str(self.name))
        self.compartments[self.inputCompartmentName()] = inp

    @property
    def pressure(self):
        return self.compartments.get(self.pressureName(), None)

    @pressure.setter
    def pressure(self, inp):
        if inp is not None:
            if inp.shape[1] != self.n_units:
                raise RuntimeError(
                    "Pressure compartment size does not match provided input size " + str(inp.shape) + "for "
                    + str(self.name))
        self.compartments[self.pressureName()] = inp

    @property
    def rateActivity(self):
        return self.compartments.get(self.rateActivityName(), None)

    @rateActivity.setter
    def rateActivity(self, out):
        if out is not None:
            if out.shape[1] != self.n_units:
                raise RuntimeError(
                    "Rate activity compartment size (n, " + str(self.n_units) + ") does not match provided output size "
                    + str(out.shape) + " for " + str(self.name))
        self.compartments[self.rateActivityName()] = out

    @property
    def activity(self):
        return self.compartments.get(self.outputCompartmentName(), None)

    @activity.setter
    def activity(self, out):
        if out is not None:
            if out.shape[1] != self.n_units:
                raise RuntimeError(
                    "Activity compartment size (n, " + str(self.n_units) + ") does not match provided output size "
                    + str(out.shape) + " for " + str(self.name))
        self.compartments[self.outputCompartmentName()] = out

    # Define Functions
    def __init__(self, name, n_units, tau_m, leakRate=0., act_fx="identity",
                 key=None, useVerboseDict=False, directory=None, **kwargs):
        super().__init__(name, useVerboseDict, **kwargs)

        ##Random Number Set up
        self.key = key
        if self.key is None:
            self.key = random.PRNGKey(time.time_ns())

        ## membrane parameter setup (affects ODE integration)
        self.tau_m = tau_m ## membrane time constant -- setting to 0 triggers "stateless" mode
        self.leakRate = leakRate ## degree to which rate neurons leak

        ##Layer Size Setup
        self.n_units = n_units
        self.batch_size = 1

        self.fx, self.dfx = create_function(fun_name=act_fx)

        ## Set up bundle for multiple inputs of current
        self.create_bundle('multi_input', 'additive')
        self.reset()

    def verify_connections(self):
        self.metadata.check_incoming_connections(self.inputCompartmentName(), min_connections=1)

    def advance_state(self, t, dt, **kwargs):
        if self.tau_m > 0.:
            ### run one step of Euler integration over neuronal dynamics
            ## Notes:
            ## self.pressure <-- "top-down" expectation / contextual pressure
            ## self.current <-- "bottom-up" data-dependent signal
            dfx_val = self.dfx(self.rateActivity)
            self.current = modulate(self.current, dfx_val)
            self.rateActivity = run_cell(dt, self.current, self.pressure,
                                         self.rateActivity, self.tau_m, leak_gamma=self.leakRate)
            self.activity = self.fx(self.rateActivity)
            self.current = None
        else:
            ## run in "stateless" mode (when no membrane time constant provided)
            self.rateActivity = run_cell_stateless(self.current)
            self.activity = self.fx(self.rateActivity)
            #self.current = None

    def reset(self, **kwargs):
        self.current = jnp.zeros((self.batch_size, self.n_units))
        self.pressure = jnp.zeros((self.batch_size, self.n_units))
        self.rateActivity = jnp.zeros((self.batch_size, self.n_units))
        self.activity = jnp.zeros((self.batch_size, self.n_units))

    def save(self, **kwargs):
        pass