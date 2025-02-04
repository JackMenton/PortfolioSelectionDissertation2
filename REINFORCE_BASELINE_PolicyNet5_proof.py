# -*- coding: utf-8 -*-
"""
Created on Fri Jul 17 10:50:06 2020

@author: Jack Menton

This notebook has solves the problem with a utility function and Neural Networks
for both policy and value functions
"""

import math
import numpy as np
import matplotlib.pyplot as plt
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

# set seeds for reproducability
np.random.seed(0)
torch.manual_seed(0)

dt = 1/52 #  time increments
T = 2*dt # time horizon
x_0 = 1.0 # initial wealth
N = math.floor(T/dt) # number of time steps
EPOCHS = 5000 # number of training episodes

# Some Parameters
mu = 0.1 # drift of stock
sigma = 0.1 # volatility of stock
r =  0.02 # risk free rate
rho = (mu - r)/sigma # sharpe ratio
lam = 0.001 # temperature parameter for entropy
z = 1.1 # desired rate of return (Only important in the Mean Variance investment case)
gamma = 0.5 # gamma for power utility function

true_mean  = (rho)/(sigma*(1-gamma))


class PolicyNetwork(nn.Module):
    ''' Neural Network for the policy, which is taken to be normally distributed hence
    this network returns a mean and variance - inputs are current wealth and time 
    left in investment horizon'''
    def __init__(self, lr, input_dims, fc1_dims, fc2_dims, n_returns):
        super(PolicyNetwork, self).__init__()
        self.input_dims = input_dims
        self.fc1_dims = fc1_dims
        self.fc2_dims = fc2_dims
        self.n_returns = n_returns
        self.lr = lr
        self.fc1 = nn.Linear(*self.input_dims, self.fc1_dims) # inputs should be wealth and time to maturity
        self.fc2 = nn.Linear(self.fc1_dims,self.fc2_dims)
        self.fc3 = nn.Linear(self.fc2_dims,n_returns) # returns mean and sd of normal dist
        self.optimizer = optim.Adam(self.parameters(), lr = lr)
        
    def forward(self, observation):
        state = torch.Tensor(observation).float().unsqueeze(0)
        x = F.leaky_relu(self.fc1(state), negative_slope=0.1) # no restrictions on first two layers
        x = F.leaky_relu(self.fc2(x), negative_slope=0.1)
        x = self.fc3(x)
        first_slice = x[:,0]
        second_slice = x[:,1]
        tuple_of_activated_parts = (
                first_slice, # let mean be negative
                #F.relu(first_slice), # make sure mean is positive
                #torch.sigmoid(second_slice) # make sure sd is positive
                F.softplus(second_slice) # make sd positive but dont trap below 1
                )
        out = torch.cat(tuple_of_activated_parts, dim=-1)
        return out
            
class ValueFuncNetwork(nn.Module):
    ''' Neural Network for estimating the value function - inputs are current wealth
    and time left in investment horizon, outputs are value function approximation for 
    input state'''
    def __init__(self, lr, input_dims, fc1_dims, fc2_dims, n_returns):
        super(ValueFuncNetwork, self).__init__()
        self.input_dims = input_dims
        self.fc1_dims = fc1_dims
        self.fc2_dims = fc2_dims
        self.n_returns = n_returns
        self.lr = lr
        self.fc1 = nn.Linear(*self.input_dims, self.fc1_dims) # input is wealth and time to maturity 
        self.fc2 = nn.Linear(self.fc1_dims,self.fc2_dims)
        self.fc3 = nn.Linear(self.fc2_dims,n_returns) # output is value of the state
        self.optimizer = optim.Adam(self.parameters(), lr = lr)
        
    def forward(self, observation):
        state = torch.Tensor(observation).float()
        x = F.leaky_relu(self.fc1(state), negative_slope=0.01)
        x = F.leaky_relu(self.fc2(x), negative_slope=0.01)
        x = F.leaky_relu(self.fc3(x), negative_slope=0.01) # leaky relu to help with derivs
        return x     
    
class Agent(object):
    ''' Investment agent class '''
    def __init__(self, alpha, beta, input_dims, gamma = 1, l1_size = 256, l2_size = 256):
        self.gamma = gamma
        self.reward_memory = [] #  to store episodes rewards
        self.action_memory = [] # to store episodes actions
        self.value_memory = [] # to store value of being in each state
        self.mean_memory = []
        self.sd_memory = []
        self.value = ValueFuncNetwork(beta, input_dims, l1_size, l2_size, n_returns = 1)
        self.policy = PolicyNetwork(alpha, input_dims, l1_size, l2_size, n_returns = 2)
        
    def choose_action(self, current_wealth, t):
        '''Inputs a state of environment, returns an allocation weight '''
        state = [current_wealth, T-t]
        self.mean, self.sd = self.policy.forward(state) # calculate mean and sd of policy 
        action_dist = torch.distributions.normal.Normal(self.mean,self.sd) # define distribution
        action = action_dist.sample() # sample from distribution     
        log_probs = action_dist.log_prob(action) # obtain log_probs of the action
        self.action_memory.append(log_probs) # store log probs
        self.reward = lam*action_dist.entropy().item() # store running reward which is entropy at current time step
        
        return action.item()
    
    def get_value(self, current_wealth, t):
        ''' get value of state'''
        state = [current_wealth, T-t]
        value_ = self.value.forward(state)
        return value_
    
    def store_value(self, value):
        '''store values'''
        self.value_memory.append(value)
    
    def store_rewards(self, reward):
        '''store rewards'''
        self.reward_memory.append(reward)
    
    def store_means(self, mean):
        '''store rewards'''
        self.mean_memory.append(mean)

    def store_sds(self, sd):
        '''store rewards'''
        self.sd_memory.append(sd)
        
    def learn(self):
        '''learn - done after each episode'''
        self.policy.optimizer.zero_grad()
        self.value.optimizer.zero_grad()
        
        deltas = [] # to store delta values
        G = [] # to store gain values
        
        # Populate accumulated rewards list
        for j in range(N):
            R = 0
            for k in range(j,N):
                R += self.reward_memory[k+1]
            G.append(R)
            
        # Populate delta list
        for j in range(N):
            deltas.append(G[j] - self.value_memory[j].item())
            
        self.score = G[0] # Score - expected episode rewards (in inital state)
       
        # Code to standardize deltas where appropriate
        #mean = np.mean(deltas)
        #std = np.std(deltas) if np.std(deltas) > 0 else 1
        #deltas = (deltas-mean)/std
        
        
        
        '''obtain total losses'''
        val_loss = 0
        for d, vals in zip(deltas, self.value_memory):
            val_loss += -d*vals
        
        policy_loss = 0
        for d, logprob in zip(deltas, self.action_memory):
            policy_loss += -d*logprob
            
        total_loss = (val_loss + policy_loss)
        total_loss.backward() # compute gradients
        
        # take update steps
        self.value.optimizer.step() 
        self.policy.optimizer.step()
        
        # empty caches
        self.reward_memory = []
        self.action_memory = []
        self.value_memory = []

    
def wealth( x, sample):
    '''obtain new wealth sample - this is case where equity is GBM'''
    x_new =  x + sigma*sample*(rho*dt + np.sqrt(dt)*np.random.randn())
    return x_new

def util(x):
    '''utility function'''
    return x**gamma

def true_value(x, t):
    ''' True value function for x**gamma utility and no entropy regularization '''
    beta = (gamma*rho**2)/(2*(1-gamma))
    y = np.exp(beta*(T-t))*x**gamma
    return y

def true_mean(x):
    ''' Optimal control for x**gamma utility and no entropy regularization '''
    y = (rho*x)/(sigma*(1-gamma))
    return y 


def surface_plot(matrix1, matrix2, x_vec, y_vec, **kwargs):
    ''' Function to create 3d plot '''
    (x, y) = np.meshgrid(x_vec, y_vec)
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')
    surf1 = ax.plot_surface(x, y, matrix1, label = 'Approximated Surface', **kwargs)
    surf2 = ax.plot_surface(x, y, matrix2, label = 'True Surface', **kwargs)
    return (fig, ax, surf1, surf2)
# ------ Main ------ # 
'''
    Learning rates:
        lam = 2 , alpha = 0.001, beta = 0.001, T = 26*dt, linear utility
        lam = 0, alpha = 0.075 , beta = 0.075, T = 26*dt, x**(0.5) utility
        lam = 0, alpha = 0.01 , beta = 0.01, T = dt, x**(0.5) utility
        lam= 0.1, alpha = 0.6, beta = 0.6, T = 26*dt, x**(0.5) utility
        lam= 0.1, alpha = 0.1, beta = 0.1, T = 26*dt, x**(0.5) utility
        **lam = 0.001, alpha = 0.075, beta = 0.05, T = 2*dt, x**(0.5) utility
        
    Individually:
        best lr for value function was found to be about 0.01
        best ''                                        '' 0.35
'''
agent = Agent(alpha = 0.005, beta = 0.005, input_dims = [2], gamma = 1, l1_size = 32, l2_size = 32)
# alpha is policy network learning rate
# beta is value network learning rate

# -------------- TRAINING ----------- #
episode_scores = np.array([]) # stores score of agent across episodes
episode_values = [] # stores value of initial state for each episode
for epoch in range(EPOCHS):
    episode_wealths = [] # stores trajectory of wealth for current episode
    #curr_wealth = x_0 
    curr_wealth = np.random.uniform(0.0,1.5) # initial wealth of episode
    for i in range(N):
        t = i*dt
        episode_wealths.append(curr_wealth)
        value = agent.get_value( curr_wealth, t) # get value of current state from NN
        agent.store_value(value) # store this value
        action = agent.choose_action( curr_wealth, t) # obtain an action
        agent.store_rewards(agent.reward) # store reward from taking this action
        new_wealth = wealth(curr_wealth, action) # observe new wealth
        if i == 0:
            # Store mean, sd and value of this episodes inital state
            episode_values.append(value.item())
            agent.store_sds(agent.sd.item())
            agent.store_means(agent.mean.item())
        if new_wealth < 0:
            # Break code in the case that wealth falls below zero
            new_wealth = 0
        curr_wealth = new_wealth # set new wealth to current wealth
        if curr_wealth == 0:
            for k in range(N-1-i):
                agent.store_rewards(0)
                agent.store_value(torch.Tensor([0]))
            break
    agent.store_rewards(util(new_wealth)) # add terminal wealth to episodes rewards list
                 
    agent.learn() # perform learning steps
    episode_scores = np.append(episode_scores,agent.score) # store agent score for this episode

# ----------- TESTING ---------- #
# Some code to test a trained model
'''
terminal_wealths = []
for epoch in range(int(EPOCHS/10)):
    episode_wealths = []
    curr_wealth = x_0
    for i in range(N):
        t = i*dt
        episode_wealths.append(curr_wealth)
        action = agent.choose_action( curr_wealth, t) # choose actions 
        new_wealth = wealth(curr_wealth, action) # obtain new wealth
        if new_wealth < 0:
            new_wealth = 0
        curr_wealth = new_wealth # set new wealth to current wealth
        if curr_wealth == 0:
            break
    terminal_wealths.append(new_wealth)

mean_tw = np.mean(terminal_wealths)
'''

# This is where .grad is stored
value_params = list(agent.value.parameters()) 
policy_params = list(agent.policy.parameters())

# ---------- Plotting ----------- #
textstr = '\n'.join((
    r'$\mu=%.2f$' % (mu, ),
    r'$r=%.2f$' % (r, ),
    r'$\sigma=%.2f$' % (sigma, ),
    r'$\rho=%.2f$' % (rho, ),
    r'$\lambda=%.2f$' % (lam, )))



'''
#Plots the episode scores
plt.figure()
plt.plot(range(EPOCHS), episode_scores)
plt.title('Learning Curve for Reinforce with Baseline - T = 0.5 year')
plt.xlabel('Episodes')
plt.ylabel('G_0 - total reward on episode')
'''

'''
# Plots terminal wealths of testing phase
plt.figure()
plt.plot(range(EPOCHS), terminal_wealths)
plt.title('Terminal Wealth - T = 0.5 year')
plt.xlabel('Episodes')
plt.ylabel('Terminal Wealth')
'''

# Plots the mean of the policy distribution of the inital state across episodes
# Means should theoretically converge to red line for small values of lambda
plt.figure()
plt.plot(range(EPOCHS), agent.mean_memory, label = 'episode mean control')
plt.axhline(y=true_mean(x_0), color='r', linestyle='-', label = 'optimal control')
plt.title('Learning Curve Mean of Policy Distribution (of initial state)')
plt.xlabel('Episodes')
plt.ylabel('Mean')
plt.text(EPOCHS-(EPOCHS/10),2.5, textstr)
plt.legend()

'''
# Plots sd across episodes - sd's should converge to 0 for small values of lambda
plt.figure()
plt.plot(range(EPOCHS), agent.sd_memory)
plt.title('Learning Curve SD of Policy Distribution')
plt.xlabel('Episodes')
plt.ylabel('sd')
'''

# Plots the value of the initial state across episodes - should converge to red line for small lambda
plt.figure()
plt.plot(range(EPOCHS), episode_values, label = 'episode values')
plt.axhline(y=true_value(1,0), color='r', linestyle='-', label = 'optimal value')
plt.title('Value Network Convergence (of initial state)')
plt.xlabel('Episodes')
plt.ylabel('value of inital state')
plt.text(EPOCHS-(EPOCHS/10),0.2, textstr)
plt.legend()

# ------- 3D Surface Splot -------- #
# Plots value function surface

'''
x_points = list(np.linspace(0.0, 1.2, 100))
t_points = list(np.linspace(0, T, 100))
tmat_points = [T-i for i in t_points]
values = np.zeros((len(x_points),len(t_points)))
true_values = np.zeros((len(x_points),len(t_points)))
mean_values = []
true_means = []

xg,tg = np.meshgrid(x_points,tmat_points)

for i in range(len(t_points)):
    for j in range(len(x_points)):
        values[i,j] = agent.value.forward(torch.Tensor([x_points[j],tmat_points[i]]))
        true_values[i,j] = true_value(x_points[j], t_points[i])
        
for i in range(len(x_points)):
    mean_values.append(agent.policy([x_points[i],0])[0].item())
    true_means.append(true_mean(x_points[i]))

(fig, ax, surf1, surf2) = surface_plot(values, true_values, x_points, tmat_points)#, cmap=plt.cm.coolwarm)
#(fig1,ax1,surf1) = surface_plot(true_values, x_points, tmat_points)

#fig.colorbar(surf1)
#fig.colorbar(surf2)

ax.set_xlabel('Wealth (cols)')
ax.set_ylabel('T-t (rows)')
ax.set_zlabel('Value')
#fake2Dline = mpl.lines.Line2D([0],[0], linestyle="none", c='b', marker = 'o')
fake2Dline2 = mpl.lines.Line2D([0],[0], linestyle="none", c='r', marker = 'o')
#ax.legend([fake2Dline], ['True Surface'], numpoints = 1)
ax.legend([fake2Dline2], ['True Surface'], numpoints = 1)


plt.show()
'''

